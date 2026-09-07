"""Szigorú CSV/XLSX költségvetés-import tesztjei — Task75.

Fail-closed esetek: képlet, makró, külső hivatkozás, ismétlődő kód, hibás
fejléc, méret-/sor-/oszlopkorlát, vegyes devizanem, amount_basis szabályok,
preview utáni változás és nem-draft célterv. Kizárólag szintetikus fixture-ek.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models import ProjectBudgetImport, ProjectFinanceBudgetLine, ProjectFinancePlan
from app.services.budget_import import (
    BudgetImportError,
    approve_budget_import,
    parse_budget_file,
    preview_budget_import,
)

HEADERS = [
    "cost_code",
    "category",
    "description",
    "amount",
    "currency",
    "cost_class",
    "direct_cost_component",
    "amount_basis",
    "is_summary_package",
    "parent_summary_line_id",
]


def _row(code, *, amount="1000000", cost_class="direct", component="material", basis="", summary="false", parent="", currency=""):
    return [
        code, "szerkezet", f"{code} teszt sor", amount, currency,
        cost_class, component, basis, summary, parent,
    ]


def _csv_bytes(rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _xlsx_bytes(rows, *, formula_cell: tuple | None = None, extra_zip_entries: tuple = ()) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    if formula_cell:
        sheet.cell(row=formula_cell[0], column=formula_cell[1]).value = "=SUM(A1:A2)"
    buffer = io.BytesIO()
    workbook.save(buffer)
    data = buffer.getvalue()
    if extra_zip_entries:
        buffer2 = io.BytesIO()
        with zipfile.ZipFile(buffer2, "w") as archive:
            archive.writestr("placeholder", b"")
            with zipfile.ZipFile(io.BytesIO(data)) as source:
                for name in source.namelist():
                    archive.writestr(name, source.read(name))
            for name in extra_zip_entries:
                archive.writestr(name, b"x")
        data = buffer2.getvalue()
    return data


def _draft_plan(db, *, project_id="IMP-IMPORT-001", plan_id="FIN-PLAN-IMPORT-01"):
    plan = ProjectFinancePlan(plan_id=plan_id, project_id=project_id, version=1, status="draft", currency="HUF", contract_revenue_net=Decimal("10000000"), created_by="fixture@imperial.local",)
    db.add(plan)
    db.commit()
    return plan


def _user(role: str, email: str | None = None):
    from types import SimpleNamespace
    return SimpleNamespace(role=role, email=email or f"{role}@imperial.local")


def _approve(db, row, plan, *, role="finance", user_email=None):
    # Task79: a jóváhagyó szolgáltatáshívás kötelezően actor-kontextust visz.
    return approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id,
        actor=user_email or f"{role}@imperial.local", actor_role=role,
        user=_user(role, user_email or f"{role}@imperial.local"),)


def _happy_rows():
    return [
        _row("FOUNDATION", amount="6000000", component="other", basis="NET_REVENUE_ENVELOPE", summary="true"),
        _row("MAT-BRICK", amount="2000000", parent="FOUNDATION"),
    ]


# --- Sikeres utak ---


def test_csv_preview_and_approve_applies_classified_lines(db):
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="budget.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    assert row.status == "preview"
    assert row.row_count == 2 and len(row.content_sha256) == 64
    assert json.loads(row.error_json) == []
    plan = _draft_plan(db)
    approved = _approve(db, row, plan)
    assert approved.status == "approved"
    lines = list(db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id)).all())
    by_code = {line.cost_code: line for line in lines}
    assert set(by_code) == {"FOUNDATION", "MAT-BRICK"}
    assert by_code["FOUNDATION"].is_summary_package is True
    assert by_code["FOUNDATION"].amount_basis == "NET_REVENUE_ENVELOPE"
    assert by_code["MAT-BRICK"].parent_summary_line_id == by_code["FOUNDATION"].line_id
    assert by_code["MAT-BRICK"].cost_class == "direct"
    provenance = json.loads(plan.provenance_json)
    assert provenance["budget_imports"][0]["import_id"] == row.import_id


def test_xlsx_preview_passes_without_formulas(db):
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="budget.xlsx", data=_xlsx_bytes(_happy_rows()), actor="fixture@imperial.local",)
    assert row.status == "preview" and row.source_format == "xlsx"
    assert row.row_count == 2


def test_empty_currency_normalized_to_huf(db):
    rows = [_row("MAT-BRICK", amount="100", currency=""), _row("MAT-STEEL", amount="200")]
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(rows), actor="fixture@imperial.local",)
    assert row.status == "preview"
    preview = json.loads(row.preview_json)
    assert all(entry["currency"] == "HUF" for entry in preview["rows"])


# --- Fail-closed elutasítások ---


def _extra_columns_csv() -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(HEADERS + [f"EXTRA-{i}" for i in range(31)])
    writer.writerow(_row("A") + ["x"] * 31)
    return buffer.getvalue().encode("utf-8-sig")


def _indirect_child_rows():
    return [
        _row("PACK-X", amount="6000000", component="other", basis="NET_REVENUE_ENVELOPE", summary="true"),
        _row("CHILD-Y", cost_class="indirect", component="", parent="PACK-X"),
    ]


@pytest.mark.parametrize(
    "file_name,data_builder,expected_code",
    [
        ("budget.csv", lambda: _csv_bytes([_row("A", amount="=1+1")]), "formula_content"),
        ("budget.csv", lambda: _csv_bytes([_row("A", amount="@SUM(A1)")]), "formula_content"),
        ("budget.csv", lambda: _csv_bytes([_row("A", amount="+1+1")]), "formula_content"),
        ("budget.xlsx", lambda: _xlsx_bytes(_happy_rows(), formula_cell=(2, 4)), "formula_content"),
        ("budget.xlsx", lambda: _xlsx_bytes(_happy_rows(), extra_zip_entries=("xl/vbaProject.bin",)), "macro_content"),
        ("budget.xlsx", lambda: _xlsx_bytes(_happy_rows(), extra_zip_entries=("xl/externalLinks/externalLink1.xml",)), "external_links"),
        ("budget.xlsm", lambda: _xlsx_bytes(_happy_rows()), "unsupported_format"),
        ("budget.txt", lambda: b"text", "unsupported_format"),
        ("budget.csv", lambda: _csv_bytes([_row("A"), _row("A")]), "duplicate_cost_code"),
        ("budget.csv", lambda: _csv_bytes([_row("", amount="1")]), "missing_cost_code"),
        ("budget.csv", lambda: _csv_bytes([_row("A", amount="nem-szam")]), "invalid_numeric"),
        ("budget.csv", lambda: _csv_bytes([_row("A", amount="99999999999999999.99")]), "amount_overflow"),
        ("budget.csv", lambda: _csv_bytes([_row("A", amount="-5")]), "negative_value"),
        ("budget.csv", lambda: _csv_bytes([_row("A", currency="EUR")]), "currency_mismatch"),
        ("budget.csv", lambda: _csv_bytes([_row("A", cost_class="valami-mas")]), "unclassified_budget_line"),
        ("budget.csv", lambda: _csv_bytes([_row("A", component="")]), "invalid_direct_component"),
        ("budget.csv", lambda: _csv_bytes([_row("A", summary="true", basis="")]), "missing_amount_basis"),
        ("budget.csv", lambda: _csv_bytes([_row("A", basis="DIRECT_COST_BASELINE")]), "amount_basis_on_non_summary"),
        ("budget.csv", lambda: _csv_bytes([_row("A", parent="NINCS-ILYEN")]), "unknown_parent_summary"),
        ("budget.csv", lambda: _csv_bytes([_row("A", cost_class="indirect", component="material")]), "component_on_indirect"),
        ("budget.csv", lambda: _csv_bytes([_row("A", summary="true", parent="X", basis="NET_REVENUE_ENVELOPE")]), "summary_with_parent"),
        ("budget.csv", lambda: _csv_bytes(_indirect_child_rows()), "indirect_child"),
        ("budget.csv", lambda: _csv_bytes([_row("A")[:2] + ["x" * 501] + _row("A")[3:]]), "description_too_long"),
        ("budget.csv", lambda: b"\xff\xfe\x00binary", "invalid_encoding"),
        ("budget.csv", lambda: b"", "empty_file"),
        ("budget.csv", _extra_columns_csv, "too_many_columns"),
    ],
)
def test_preview_rejects_hazardous_or_invalid_inputs(db, file_name, data_builder, expected_code):
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name=file_name, data=data_builder(), actor="fixture@imperial.local",)
    assert row.status == "rejected"
    errors = json.loads(row.error_json)
    assert any(error["code"] == expected_code for error in errors)


def test_preview_rejects_mixed_amount_basis(db):
    rows = [
        _row("PACK-1", amount="100", component="other", basis="NET_REVENUE_ENVELOPE", summary="true"),
        _row("PACK-2", amount="100", component="other", basis="DIRECT_COST_BASELINE", summary="true"),
    ]
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(rows), actor="fixture@imperial.local",)
    assert row.status == "rejected"
    assert any(e["code"] == "mixed_amount_basis" for e in json.loads(row.error_json))


def test_preview_rejects_wrong_or_duplicate_headers(db):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(HEADERS[:-1])
    writer.writerow(_row("A")[:-1])
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=buffer.getvalue().encode("utf-8-sig"), actor="fixture@imperial.local",)
    assert row.status == "rejected"
    assert any(e["code"] == "invalid_headers" for e in json.loads(row.error_json))

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(HEADERS + ["cost_code"])
    writer.writerow(_row("A") + ["extra"])
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=buffer.getvalue().encode("utf-8-sig"), actor="fixture@imperial.local",)
    assert row.status == "rejected"
    assert any(e["code"] == "duplicate_headers" for e in json.loads(row.error_json))


def test_preview_rejects_oversize_file(db):
    data = b"x" * (1_000_001)
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=data, actor="fixture@imperial.local",)
    assert row.status == "rejected"
    assert any(e["code"] == "file_too_large" for e in json.loads(row.error_json))


def test_preview_rejects_too_many_rows(db):
    rows = [_row(f"CODE-{index}") for index in range(501)]
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(rows), actor="fixture@imperial.local",)
    assert row.status == "rejected"
    assert any(e["code"] == "too_many_rows" for e in json.loads(row.error_json))


def test_parse_budget_file_raises_directly_on_hazards(db):
    with pytest.raises(BudgetImportError) as excinfo:
        parse_budget_file("b.csv", _csv_bytes([_row("A", amount="=1+1")]))
    assert excinfo.value.errors[0]["code"] == "formula_content"


# --- Jóváhagyási kapuk ---


def test_approve_rejected_or_changed_import_blocks(db):
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes([_row("A", amount="=1+1")]), actor="fixture@imperial.local",)
    plan = _draft_plan(db)
    with pytest.raises(ValueError, match="Csak hibátlan preview"):
        _approve(db, row, plan)
    # A preview után megváltozott bemenet fail-closed elutasítás.
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    tampered = json.loads(row.preview_json)
    tampered["rows"][0]["amount"] = "999999999"
    row.preview_json = json.dumps(tampered, ensure_ascii=False)
    db.commit()
    with pytest.raises(ValueError, match="megváltozott"):
        _approve(db, row, plan)


def test_approve_to_approved_plan_blocks(db):
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    plan = _draft_plan(db)
    plan.status = "approved"
    db.commit()
    with pytest.raises(ValueError, match="draft"):
        _approve(db, row, plan)


def test_approve_requires_finance_role(db):
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    plan = _draft_plan(db)
    with pytest.raises(PermissionError):
        approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id, actor="fixture@imperial.local", actor_role="project-manager",)


def test_approve_unknown_import_or_plan_key_errors(db):
    plan = _draft_plan(db)
    with pytest.raises(KeyError):
        approve_budget_import(db, import_id="NINCS", plan_id=plan.plan_id, actor="fixture-finance@imperial.local", actor_role="finance",)
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    with pytest.raises(KeyError):
        approve_budget_import(db, import_id=row.import_id, plan_id="NINCS-PLAN", actor="fixture-finance@imperial.local", actor_role="finance", user=_user("finance", "fixture-finance@imperial.local"),)


# --- Task79: szolgáltatás-szintű projekt-jogosultság ---


def test_approve_without_actor_context_fails_closed(db):
    # Közvetlen hívás actor-kontextus nélkül: PermissionError, mutáció nélkül.
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    plan = _draft_plan(db)
    with pytest.raises(PermissionError):
        approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id, actor="fixture-finance@imperial.local", actor_role="finance",)
    assert db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == row.import_id)).status == "preview"
    assert len(list(db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id)).all())) == 0


def test_approve_enforces_user_context_project_scope(db):
    # A HITELESÍTETT user-kontextus projektjoga dönt: a kanonikus körön kívül
    # PermissionError mutáció nélkül, a körön belül a jóváhagyás lefut.
    from app.models import ProjectRegistry
    row = preview_budget_import(db, project_id="IMP-IMPORT-001", file_name="b.csv", data=_csv_bytes(_happy_rows()), actor="fixture@imperial.local",)
    plan = _draft_plan(db)
    with pytest.raises(PermissionError):
        approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id,
            actor="fixture-finance@imperial.local", actor_role="finance",
            user=_user("project-manager", "pm-other@imperial.local"),)
    assert db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == row.import_id)).status == "preview"
    assert len(list(db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id)).all())) == 0
    db.add(ProjectRegistry(project_id="IMP-IMPORT-001", name="Szintetikus projekt", responsible="pm-canon@imperial.local",))
    db.commit()
    approved = approve_budget_import(db, import_id=row.import_id, plan_id=plan.plan_id,
        actor="fixture-finance@imperial.local", actor_role="finance",
        user=_user("project-manager", "pm-canon@imperial.local"),)
    assert approved.status == "approved"
