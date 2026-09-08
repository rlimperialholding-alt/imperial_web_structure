"""Szigorú, fail-closed szintetikus CSV/XLSX költségvetés-import (Task75).

Korlátok: kiterjesztés/méret/sor/oszlop/felirat; képlet (xlsx cella, CSV
'='/@/+ kezdet), makró (vbaProject.bin) és külső hivatkozás elutasítása;
pontos fejlécsor, ismétlődő fejléc/költségkód elutasítása; nettó HUF
normalizáció (nincs rejtett árfolyamváltás); amount_basis kizárólag összegző
soron, ott kötelező; content-hash a nyers fájlra, preview_sha256 a tárolt
preview-ra („preview után megváltozott bemenet" determinisztikusan
elutasított); jóváhagyás kizárólag draft tervre, provenance-nyommal — az
import soha nem hoz létre jóváhagyott tervet.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (ProjectBudgetImport, ProjectFinanceBudgetLine, ProjectFinancePlan,)
from .project_finance import require_project_finance_scope
from .tender_margin_gate import (AMOUNT_BASES, COST_CLASSES, DIRECT_COMPONENTS, MarginGateBlocked, _id, canonical_json, sha256_hex, utcnow,)

MAX_UPLOAD_BYTES = 1_000_000
MAX_DATA_ROWS = 500
MAX_COLUMNS = 40
MAX_DESCRIPTION_LEN = 500
MAX_COST_CODE_LEN = 100
MAX_AMOUNT = Decimal("9999999999999999.99")

REQUIRED_HEADERS = ("cost_code",
    "category",
    "description",
    "amount",
    "currency",
    "cost_class",
    "direct_cost_component",
    "amount_basis",
    "is_summary_package",
    "parent_summary_line_id",)

IMPORT_ROLES = {"finance", "managing-director", "owner", "platform-admin"}


class BudgetImportError(ValueError):
    """Fail-closed import-hiba: az import rögzítése rejected állapotban történik."""

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__("; ".join(error["message"] for error in errors[:5]))


def _fail(message: str, row: int | None = None, code: str = "invalid_row") -> dict[str, Any]:
    return {"row": row, "code": code, "message": message}


def _parse_amount(value: str, row_no: int) -> Decimal:
    text = (value or "").strip().replace(",", ".")
    if not text:
        raise BudgetImportError([_fail("Hiányzó összeg.", row_no, "missing_amount")])
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        raise BudgetImportError([_fail("Érvénytelen numerikus összeg.", row_no, "invalid_numeric")]) from None
    if not amount.is_finite():
        raise BudgetImportError([_fail("Az összeg nem lehet NaN/Inf.", row_no, "invalid_numeric")])
    if amount < 0:
        raise BudgetImportError([_fail("Az összeg nem lehet negatív.", row_no, "negative_value")])
    if amount > MAX_AMOUNT:
        raise BudgetImportError([_fail("Az összeg meghaladja a mezőkorlátot.", row_no, "amount_overflow")])
    return amount.quantize(Decimal("0.01"))


def _parse_bool(value: str, row_no: int) -> bool:
    text = (value or "").strip().lower()
    if text in {"true", "1", "igen"}:
        return True
    if text in {"false", "0", "nem"}:
        return False
    raise BudgetImportError([_fail("Érvénytelen logikai érték (true/false).", row_no, "invalid_boolean")])


def _validate_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], str]:
    """Sorok validálása és nettó HUF normalizáció; bármely hiba az egész
    importot fail-closed elutasítja."""
    normalized: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    summary_codes: set[str] = set()
    child_parents: set[str] = set()
    file_amount_bases: set[str] = set()
    for index, row in enumerate(rows, start=2):
        cost_code = (row.get("cost_code") or "").strip()
        if not cost_code:
            raise BudgetImportError([_fail("Hiányzó költségkód.", index, "missing_cost_code")])
        if len(cost_code) > MAX_COST_CODE_LEN:
            raise BudgetImportError([_fail("Túl hosszú költségkód.", index, "cost_code_too_long")])
        if cost_code in seen_codes:
            raise BudgetImportError([_fail("Ismétlődő költségkód.", index, "duplicate_cost_code")])
        seen_codes.add(cost_code)
        currency = (row.get("currency") or "").strip().upper()
        if currency not in {"", "HUF"}:
            raise BudgetImportError([_fail("A devizanem csak HUF lehet; átváltatlan összeg nem importálható.", index, "currency_mismatch")])
        currency = "HUF"
        cost_class = (row.get("cost_class") or "").strip().lower()
        if cost_class not in COST_CLASSES:
            raise BudgetImportError([_fail("A besorolás direct/indirect kötelező.", index, "unclassified_budget_line")])
        is_summary = _parse_bool(row.get("is_summary_package") or "", index)
        component = (row.get("direct_cost_component") or "").strip().lower()
        if cost_class == "direct":
            if component not in DIRECT_COMPONENTS:
                raise BudgetImportError([_fail("Direct sorhoz kötelező a költségnem (anyag/munkabér/gép/egyéb).", index, "invalid_direct_component")])
        elif component:
            raise BudgetImportError([_fail("Indirect sorhoz nem adható meg direct költségnem.", index, "component_on_indirect")])
        amount_basis = (row.get("amount_basis") or "").strip().upper()
        if is_summary:
            if amount_basis not in AMOUNT_BASES:
                raise BudgetImportError([_fail("Összegző csomagsorhoz kötelező az explicit amount_basis.", index, "missing_amount_basis")])
            summary_codes.add(cost_code)
            file_amount_bases.add(amount_basis)
        elif amount_basis:
            raise BudgetImportError([_fail("Az amount_basis kizárólag összegző csomagsoron adható meg.", index, "amount_basis_on_non_summary")])
        parent = (row.get("parent_summary_line_id") or "").strip()
        if is_summary and parent:
            raise BudgetImportError([_fail("Egy sor nem lehet egyszerre csomag és gyereksor.", index, "summary_with_parent")])
        if parent and cost_class != "direct":
            raise BudgetImportError([_fail("A gyereksor csak direct besorolású lehet.", index, "indirect_child")])
        if parent:
            child_parents.add(parent)
        description = (row.get("description") or "").strip()
        if not description:
            raise BudgetImportError([_fail("Hiányzó leírás.", index, "missing_description")])
        if len(description) > MAX_DESCRIPTION_LEN:
            raise BudgetImportError([_fail("Túl hosszú leírás.", index, "description_too_long")])
        normalized.append({
                "cost_code": cost_code,
                "category": (row.get("category") or "").strip()[:120] or "egyéb",
                "description": description,
                "amount": str(_parse_amount(row.get("amount") or "", index)),
                "currency": currency,
                "cost_class": cost_class,
                "direct_cost_component": component or None,
                "amount_basis": amount_basis or None,
                "is_summary_package": is_summary,
                "parent_summary_line_id": parent or None,
            })
    unknown_parents = child_parents - summary_codes
    if unknown_parents:
        raise BudgetImportError([ _fail("A gyereksor ismeretlen összegző csomagra hivatkozik: " + ", ".join(sorted(unknown_parents)), None, "unknown_parent_summary",)
            ])
    if len(file_amount_bases) > 1:
        raise BudgetImportError([ _fail("Egy fájlban az összegző csomagsorok amount_basis értékének " "egységesnek kell lennie.", None, "mixed_amount_basis",) ])
    return normalized, (sorted(file_amount_bases)[0] if file_amount_bases else "")


def parse_budget_file(filename: str, data: bytes) -> tuple[list[dict[str, str]], list[str], str]:
    """Szigorú CSV/XLSX feldolgozás; a visszatérés (sorok, fejléc, formátum)."""
    name = (filename or "").strip().lower()
    if len(data) > MAX_UPLOAD_BYTES:
        raise BudgetImportError([_fail("A fájl meghaladja az 1 MB méretkorlátot.", None, "file_too_large")])
    if name.endswith(".csv"):
        rows, headers = _parse_csv(data)
        return rows, headers, "csv"
    if name.endswith(".xlsx"):
        _reject_xlsx_hazards(data)
        rows, headers = _parse_xlsx(data)
        return rows, headers, "xlsx"
    raise BudgetImportError([_fail("Csak .csv vagy .xlsx fájl fogadható el.", None, "unsupported_format")])


def _reject_xlsx_hazards(data: bytes) -> None:
    """Makró-, képlet- és külsőhivatkozás-elutasítás a zip-belső és a
    munkafüzet-fa alapján."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            for name in names:
                if name.startswith("xl/externalLinks/"):
                    raise BudgetImportError([_fail("Külső hivatkozást tartalmazó munkafüzet nem importálható.", None, "external_links")])
                if name == "xl/vbaProject.bin":
                    raise BudgetImportError([_fail("Makrót tartalmazó munkafüzet nem importálható.", None, "macro_content")])
    except zipfile.BadZipFile:
        raise BudgetImportError([_fail("Sérült xlsx-állomány.", None, "invalid_xlsx")]) from None


def _parse_xlsx(data: bytes) -> tuple[list[dict[str, str]], list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError:  # pragma: no cover - a runtime függőség a requirements része
        raise BudgetImportError([_fail("Az xlsx-feldolgozó nem elérhető.", None, "xlsx_unavailable")]) from None
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise BudgetImportError([_fail("Az xlsx-állomány nem olvasható.", None, "invalid_xlsx")]) from exc
    try:
        sheet = workbook.active
        for worksheet in workbook.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        raise BudgetImportError([_fail("Képletet tartalmazó munkafüzet nem importálható.", None, "formula_content")])
        rows = list(sheet.iter_rows(values_only=True))
        header_values = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
        return _collect_rows(rows, header_values), header_values
    finally:
        workbook.close()


def _collect_rows(rows: list, header_values: list[str]) -> list[dict[str, str]]:
    """Közös sorbegyűjtés (CSV/XLSX): üres sorok kihagyása, hossz- és
    sorszám-korlát, fejléchez illesztés."""
    data_rows: list[dict[str, str]] = []
    for row_index, row in enumerate(rows, start=1):
        if row_index == 1:
            continue  # fejlécsor
        if not any((cell or "").strip() for cell in row):
            continue
        values = [str(cell).strip() if cell is not None else "" for cell in row]
        if len(values) > len(header_values):
            raise BudgetImportError([_fail("A sor hosszabb a fejlécnél.", row_index, "row_longer_than_header")])
        data_rows.append(dict(zip(header_values, values)))
        if len(data_rows) > MAX_DATA_ROWS:
            raise BudgetImportError([_fail(f"A fájl több mint {MAX_DATA_ROWS} adatsort tartalmaz.", None, "too_many_rows")])
    return data_rows


def _parse_csv(data: bytes) -> tuple[list[dict[str, str]], list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise BudgetImportError([_fail("A CSV nem UTF-8 kódolású.", None, "invalid_encoding")]) from None
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        raise BudgetImportError([_fail("Üres CSV-állomány.", None, "empty_file")])
    for row in rows:
        # Képlet-injekció védelem: '=' (akár vezető szóközzel) és @/+/
        # tabulátor/CR kezdetű cella nem importálható. A '-' kezdet a
        # negatív összegek legitim jelölése, azokat a numerikus validáció
        # (negative_value) utasítja el.
        for cell in row:
            stripped = (cell or "").lstrip()
            if stripped.startswith(("=", "@", "+")) or (cell and cell[0] in ("\t", "\r")):
                raise BudgetImportError([_fail("Képlet-gyanús cella nem importálható.", None, "formula_content")])
    header_values = [str(cell).strip() for cell in rows[0]]
    return _collect_rows(rows, header_values), header_values


def _validate_headers(headers: list[str]) -> None:
    if any(not header.strip() for header in headers):
        raise BudgetImportError([_fail("Üres fejlécoszlop nem engedélyezett.", None, "empty_header")])
    cleaned = [header.strip() for header in headers]
    if len(set(cleaned)) != len(cleaned):
        raise BudgetImportError([_fail("Ismétlődő fejlécoszlop.", None, "duplicate_headers")])
    if len(cleaned) > MAX_COLUMNS:
        raise BudgetImportError([_fail(f"A fejléc több mint {MAX_COLUMNS} oszlopot tartalmaz.", None, "too_many_columns")])
    if sorted(cleaned) != sorted(REQUIRED_HEADERS):
        raise BudgetImportError([ _fail("A fejlécnek pontosan a következő oszlopokat kell tartalmaznia: " + ", ".join(REQUIRED_HEADERS), None, "invalid_headers",) ])


def preview_budget_import(db: Session, *, project_id: str, file_name: str, data: bytes, actor: str) -> ProjectBudgetImport:
    """Preview: semmilyen tervmódosítás; a rekord a parse-eredménnyel jön létre."""
    content_sha256 = hashlib.sha256(data).hexdigest()
    try:
        rows, headers, source_format = parse_budget_file(file_name, data)
        _validate_headers(headers)
        normalized, file_amount_basis = _validate_rows(rows)
    except BudgetImportError as exc:
        row = ProjectBudgetImport(import_id=_id("BIMP"), project_id=project_id, file_name=file_name[:500],
            source_format=("xlsx" if (file_name or "").strip().lower().endswith(".xlsx") else "csv"),
            content_sha256=content_sha256, preview_sha256="0" * 64, row_count=0,
            amount_basis="NET_REVENUE_ENVELOPE", currency="HUF", status="rejected",
            preview_json="{}", error_json=canonical_json(exc.errors), imported_by=actor,)
        db.add(row)
        audit(db, actor=actor, action="budget.import.rejected", entity_type="finance_budget_import", entity_id=row.import_id, after={"content_sha256": content_sha256, "errors": exc.errors[:10]},)
        db.commit()
        db.refresh(row)
        return row
    preview_json = canonical_json({"rows": normalized, "content_sha256": content_sha256, "amount_basis": file_amount_basis})
    row = ProjectBudgetImport(import_id=_id("BIMP"), project_id=project_id, file_name=file_name[:500],
        source_format=source_format, content_sha256=content_sha256,
        preview_sha256=sha256_hex(preview_json), row_count=len(normalized),
        amount_basis=file_amount_basis or "NET_REVENUE_ENVELOPE", currency="HUF",
        status="preview", preview_json=preview_json, error_json="[]", imported_by=actor,)
    db.add(row)
    audit(db, actor=actor, action="budget.import.previewed", entity_type="finance_budget_import", entity_id=row.import_id, after={"content_sha256": content_sha256, "row_count": len(normalized)},)
    db.commit()
    db.refresh(row)
    return row


def _verified_approver(user: object) -> tuple[str, str]:
    """Task80: az effective actor (email, szerepkör) KIZÁRÓLAG a hitelesített
    user-objektumból származik — külön actor/actor_role paraméter nincs, így
    önkényes ``actor_role='finance'`` vagy idegen audit-actor nem adható át;
    hiányzó kontextus, azonosítatlan user vagy nem jóváhagyó szerepkör
    fail-closed PermissionError (mutáció előtt)."""
    if user is None:
        raise PermissionError("A költségvetés-import jóváhagyása hitelesített felhasználói kontextus nélkül nem végezhető el.")
    actor = getattr(user, "email", None)
    role = getattr(user, "role", None)
    if not isinstance(actor, str) or not actor:
        raise PermissionError("A költségvetés-import jóváhagyása azonosítatlan felhasználóval nem végezhető el.")
    if role not in IMPORT_ROLES:
        raise PermissionError("A költségvetés-import jóváhagyására nincs jogosultság.")
    return actor, role


def approve_budget_import(db: Session, *, import_id: str, plan_id: str, user: object) -> ProjectBudgetImport:
    """Jóváhagyás kizárólag draft tervre, a tárolt, hash-elt preview-ból; a
    „preview után megváltozott bemenet" fail-closed elutasítás.

    Task80: a jóváhagyó actor (email, szerepkör) a SZOLGÁLTATÁSBAN a
    hitelesített user-objektumból származik — PM-felelősség önmagában soha
    nem elég; a zár utáni újrazárolt soron a status ÉS a preview_sha256 is
    újraellenőrzött (TOCTOU-védelem a védett tranzakcióban)."""
    actor, _actor_role = _verified_approver(user)
    row = db.scalar(select(ProjectBudgetImport).where(ProjectBudgetImport.import_id == import_id))
    if row is None:
        raise KeyError(import_id)
    # Task79: az import PONTOS projektjének jogosultsága a SZOLGÁLTATÁSBAN
    # ellenőrzött; actor-kontextus nélkül vagy a kanonikus projekthalmazon
    # kívül fail-closed elutasítás.
    require_project_finance_scope(db, user, row.project_id)
    if row.status != "preview":
        raise MarginGateBlocked("import_not_preview", "Csak hibátlan preview állapotú import hagyható jóvá.",)
    if sha256_hex(row.preview_json) != row.preview_sha256:
        raise MarginGateBlocked("import_changed_after_preview", "Az import tartalma a preview óta megváltozott; a jóváhagyás " "fail-closed elutasítva.",)
    # Task77 Gate7: a célterv sorzárral (FOR UPDATE) töltődik, a draft-
    # ellenőrzés a zár UTÁN fut (konkurens jóváhagyás nem írathat immutable
    # tervre); a populate_existing az elavult identitástérkép-objektumot is
    # frissíti.
    plan = db.scalar(select(ProjectFinancePlan) .where(ProjectFinancePlan.plan_id == plan_id) .with_for_update() .execution_options(populate_existing=True))
    if plan is None:
        raise KeyError(plan_id)
    # Projekt-scope (Review A HIGH / Task76): keresztprojekt-import fail-closed.
    if plan.project_id != row.project_id:
        raise MarginGateBlocked("import_plan_project_mismatch", "A költségvetés-import projektje és a célterv projektje nem " "egyezik; a jóváhagyás fail-closed elutasítva.",)
    # Task78: a tervzár UTÁN az import sor újrazárolása és a preview-állapot
    # ÚJRAELLENŐRZÉSE a védett tranzakcióban — két konkurens jóváhagyás közül
    # a második itt már approved státuszt lát, a sorok legfeljebb egyszer
    # kerülnek a tervre.
    row = db.scalar(select(ProjectBudgetImport) .where(ProjectBudgetImport.import_id == import_id) .with_for_update() .execution_options(populate_existing=True))
    if row is None:
        raise KeyError(import_id)
    if row.status != "preview":
        raise MarginGateBlocked("import_not_preview", "Csak hibátlan preview állapotú import hagyható jóvá.",)
    # Task80 (Review MEDIUM): a zár utáni újrazárolt soron a preview_sha256 is
    # ÚJRAELLENŐRZÖTT — a zár előtti ellenőrzés óta megváltoztatott preview
    # determinisztikusan elutasított (TOCTOU-védelem a védett tranzakcióban).
    if sha256_hex(row.preview_json) != row.preview_sha256:
        raise MarginGateBlocked("import_changed_after_preview", "Az import tartalma a preview óta megváltozott; a jóváhagyás " "fail-closed elutasítva.",)
    if plan.status != "draft":
        raise MarginGateBlocked("import_target_not_draft", "A költségvetés-import kizárólag draft tervre írható; jóváhagyott " "terv immutable.",)
    payload = json.loads(row.preview_json)
    applied = 0
    # Első menet: sorok felvitele; a fájlbeli szülő-költségkódokat a második
    # menet oldja fel a terv sorazonosítóira (line_id).
    pending_parents: dict[int, str] = {}
    for index, entry in enumerate(payload["rows"]):
        existing_line = db.scalar(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id, ProjectFinanceBudgetLine.cost_code == entry["cost_code"],))
        line_fields = dict(category=entry["category"],
            description=entry["description"],
            budget_net=Decimal(entry["amount"]),
            cost_class=entry["cost_class"],
            direct_cost_component=entry["direct_cost_component"],
            amount_basis=entry["amount_basis"],
            is_summary_package=bool(entry["is_summary_package"]),
            currency="HUF",
            source_type="budget_import",
            source_id=row.import_id,)
        if existing_line is None:
            existing_line = ProjectFinanceBudgetLine(line_id=_id("FBL"),
                plan_id_fk=plan.id,
                cost_code=entry["cost_code"],
                committed_net=Decimal("0"),
                actual_net=Decimal("0"),
                estimate_to_complete_net=Decimal("0"),
                **line_fields,)
            db.add(existing_line)
        else:
            existing_line.parent_summary_line_id = None
            for field, value in line_fields.items():
                setattr(existing_line, field, value)
        if entry.get("parent_summary_line_id"):
            pending_parents[index] = entry["parent_summary_line_id"]
        applied += 1
    db.flush()
    if pending_parents:
        code_to_line_id = {
            line.cost_code: line.line_id
            for line in db.scalars(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id)).all()
        }
        for index, parent_code in pending_parents.items():
            entry = payload["rows"][index]
            line = db.scalar(select(ProjectFinanceBudgetLine).where(ProjectFinanceBudgetLine.plan_id_fk == plan.id, ProjectFinanceBudgetLine.cost_code == entry["cost_code"],))
            parent_line_id = code_to_line_id.get(parent_code)
            if parent_line_id is None:
                raise MarginGateBlocked("unknown_parent_summary", "A gyereksor ismeretlen összegző csomagra hivatkozik; " "a jóváhagyás fail-closed elutasítva.",)
            if line is None:
                raise MarginGateBlocked("import_line_missing", "A gyereksor nem található a célterven; a jóváhagyás " "fail-closed elutasítva.",)
            line.parent_summary_line_id = parent_line_id
    provenance = json.loads(plan.provenance_json or "{}")
    if not isinstance(provenance, dict):
        provenance = {}
    imports = provenance.setdefault("budget_imports", [])
    imports.append({"import_id": row.import_id, "content_sha256": row.content_sha256, "applied_lines": applied})
    plan.provenance_json = canonical_json(provenance)
    row.status = "approved"
    row.approved_by = actor
    row.approved_at = utcnow()
    audit(db, actor=actor, action="budget.import.approved", entity_type="finance_budget_import", entity_id=row.import_id, after={"plan_id": plan.plan_id, "applied_lines": applied},)
    db.commit()
    db.refresh(row)
    return row
