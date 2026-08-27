from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

import app.main as main_module
from app.models import AuditLog, ProjectFinancePlan, ProjectObjectState, ProjectRegistry, TaskRecord
from app.services import project_finance as finance_service
from app.services.project_finance import (
    FinanceConcurrencyError,
    add_budget_line,
    add_cashflow_line,
    clone_finance_plan,
    create_finance_plan,
    finance_approve_plan,
    finance_plan_workspace,
    leadership_approve_plan,
    plan_summary,
    reject_finance_plan,
    submit_finance_plan,
)
from app.seed import DEMO_PASSWORD


def _user(role: str):
    return SimpleNamespace(role=role, email=f"{role}@imperial.local")


def _project(db, project_id: str) -> ProjectRegistry:
    row = ProjectRegistry(
        project_id=project_id,
        name=f"Pénzügyi UAT {project_id}",
        customer_name="Teszt Ügyfél Kft.",
        status="active",
        responsible="project-manager@imperial.local",
    )
    db.add(row)
    db.commit()
    return row


def _complete_draft(db, project_id: str, *, target: str = "20") -> ProjectFinancePlan:
    _project(db, project_id)
    plan = create_finance_plan(
        db,
        _user("project-manager"),
        project_id=project_id,
        currency="HUF",
        contract_revenue_net="100000000",
        approved_change_revenue_net="5000000",
        contingency_net="3000000",
        target_margin_percent=target,
        forecast_note="Szerződés, jóváhagyott változások és aktuális ETC alapján.",
    )
    add_budget_line(
        db,
        plan.plan_id,
        _user("project-manager"),
        cost_code="STR-001",
        category="Szerkezet",
        description="Szerkezetépítési munkacsomag",
        budget_net="65000000",
        committed_net="40000000",
        actual_net="25000000",
        estimate_to_complete_net="45000000",
        source_type="contract",
        source_id="CON-UAT-001",
    )
    add_cashflow_line(
        db,
        plan.plan_id,
        _user("project-manager"),
        period_date=date(2026, 9, 1),
        direction="inflow",
        category="Megrendelői mérföldkő",
        description="Szerkezetkész részszámla",
        amount_net="70000000",
        status="committed",
        source_type="contract",
        source_id="CON-UAT-001",
    )
    add_cashflow_line(
        db,
        plan.plan_id,
        _user("project-manager"),
        period_date=date(2026, 9, 15),
        direction="outflow",
        category="Alvállalkozó",
        description="Szerkezetépítői teljesítés",
        amount_net="45000000",
        status="forecast",
        source_type="purchase_order",
        source_id="PO-UAT-001",
    )
    db.expire_all()
    return db.scalar(select(ProjectFinancePlan).where(ProjectFinancePlan.id == plan.id))


def test_finance_mutation_queries_compile_with_postgresql_row_locks():
    captured = []

    class CaptureSession:
        def scalar(self, statement):
            captured.append(statement)
            return SimpleNamespace()

    session = CaptureSession()
    finance_service._plan(session, "FIN-LOCK-1")
    finance_service._lock_project(session, "PROJECT-LOCK-1")

    compiled = [
        str(statement.compile(dialect=postgresql.dialect())).upper()
        for statement in captured
    ]
    assert len(compiled) == 2
    assert all("FOR UPDATE" in statement for statement in compiled)


def test_finance_version_collision_is_409_ready_and_audited(db, monkeypatch):
    project_id = "FIN-CONCURRENCY-1"
    _project(db, project_id)
    real_commit = db.commit
    commit_calls = 0

    def collide_once():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise IntegrityError("INSERT finance_project_plans", {}, RuntimeError("duplicate"))
        return real_commit()

    monkeypatch.setattr(db, "commit", collide_once)
    with pytest.raises(FinanceConcurrencyError, match="frissítsen és próbálja újra"):
        create_finance_plan(
            db,
            _user("project-manager"),
            project_id=project_id,
            currency="HUF",
            contract_revenue_net="1000000",
            approved_change_revenue_net="0",
            contingency_net="0",
            target_margin_percent="20",
            forecast_note="Konkurens verzióütközés szintetikus bizonyítéka.",
        )

    assert db.scalar(
        select(AuditLog).where(AuditLog.action == "finance_plan_concurrency_conflict")
    ) is not None
    assert db.scalar(
        select(ProjectFinancePlan).where(ProjectFinancePlan.project_id == project_id)
    ) is None


def test_finance_version_collision_returns_http_409(logged_in_client, monkeypatch):
    def collision(*_args, **_kwargs):
        raise FinanceConcurrencyError("A pénzügyi tervverzió közben megváltozott.")

    monkeypatch.setattr(main_module, "create_finance_plan", collision)
    response = logged_in_client.post(
        "/financial/plans",
        data={
            "project_id": "PROJECT-RACE",
            "currency": "HUF",
            "contract_revenue_net": "1",
            "target_margin_percent": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 409


def test_project_manager_finance_plan_commands_are_project_scoped(db):
    own = ProjectRegistry(
        project_id="FIN-SCOPE-OWN",
        name="Saját tervprojekt",
        responsible="project-manager@imperial.local",
    )
    foreign = ProjectRegistry(
        project_id="FIN-SCOPE-FOREIGN",
        name="Idegen tervprojekt",
        responsible="other-manager@imperial.local",
    )
    db.add_all([own, foreign])
    db.commit()
    own_plan = create_finance_plan(
        db,
        _user("project-manager"),
        project_id=own.project_id,
        currency="HUF",
        contract_revenue_net="1000",
        approved_change_revenue_net="0",
        contingency_net="0",
        target_margin_percent="10",
        forecast_note="Saját projekt pénzügyi terve.",
    )
    foreign_plan = create_finance_plan(
        db,
        _user("finance"),
        project_id=foreign.project_id,
        currency="HUF",
        contract_revenue_net="1000",
        approved_change_revenue_net="0",
        contingency_net="0",
        target_margin_percent="10",
        forecast_note="Idegen projekt pénzügyi terve.",
    )

    workspace = finance_plan_workspace(db, user=_user("project-manager"))

    assert [item["row"].plan_id for item in workspace["plans"]] == [own_plan.plan_id]
    with pytest.raises(PermissionError, match="felelősségi körében"):
        add_budget_line(
            db,
            foreign_plan.plan_id,
            _user("project-manager"),
            cost_code="FOREIGN",
            category="Tiltott",
            description="Idegen projekt sora",
            budget_net="1",
            committed_net="0",
            actual_net="0",
            estimate_to_complete_net="1",
            source_type="test",
            source_id="FOREIGN",
        )


def test_project_finance_full_approval_creates_tasks_and_project_state(db):
    plan = _complete_draft(db, "FIN-UAT-001")
    summary = plan_summary(plan)
    assert summary["forecast_cost"] == Decimal("73000000.00")
    assert summary["forecast_margin"] == Decimal("32000000.00")
    assert summary["forecast_margin_percent"] == Decimal("30.48")
    assert summary["minimum_cash_position"] == Decimal("25000000.00")

    submit_finance_plan(db, plan.plan_id, _user("project-manager"))
    finance_approve_plan(
        db,
        plan.plan_id,
        _user("finance"),
        note="A költségsorok és források pénzügyileg ellenőrizve.",
    )
    approved = leadership_approve_plan(
        db,
        plan.plan_id,
        _user("managing-director"),
        note="A projektbaseline vezetői szempontból elfogadható.",
        margin_exception_reason="",
    )

    assert approved.status == "approved"
    assert approved.submitted_by == "project-manager@imperial.local"
    assert approved.finance_approved_by == "finance@imperial.local"
    assert approved.leadership_approved_by == "managing-director@imperial.local"
    assert approved.submitted_at and approved.finance_approved_at
    assert approved.leadership_approved_at
    state = db.scalar(
        select(ProjectObjectState).where(ProjectObjectState.object_id == plan.plan_id)
    )
    assert state and state.status == "approved"
    tasks = db.scalars(select(TaskRecord).where(TaskRecord.source_event_id == plan.plan_id)).all()
    assert len(tasks) == 2
    assert {task.status for task in tasks} == {"done"}


def test_submitted_plan_is_immutable_and_approved_plan_can_be_versioned(db):
    plan = _complete_draft(db, "FIN-UAT-002")
    submit_finance_plan(db, plan.plan_id, _user("project-manager"))
    with pytest.raises(ValueError, match="nem módosítható"):
        add_budget_line(
            db,
            plan.plan_id,
            _user("finance"),
            cost_code="NEW-001",
            category="Új",
            description="Tiltott utólagos módosítás",
            budget_net="1",
            committed_net="0",
            actual_net="0",
            estimate_to_complete_net="1",
            source_type="",
            source_id="",
        )
    finance_approve_plan(
        db,
        plan.plan_id,
        _user("finance"),
        note="A pénzügyi baseline ellenőrzése megfelelő.",
    )
    leadership_approve_plan(
        db,
        plan.plan_id,
        _user("owner"),
        note="A baseline vezetői jóváhagyása megtörtént.",
        margin_exception_reason="",
    )
    clone = clone_finance_plan(db, plan.plan_id, _user("project-manager"))
    assert clone.version == 2
    assert clone.status == "draft"
    assert len(clone.budget_lines) == 1
    assert len(clone.cashflow_lines) == 2


def test_low_margin_plan_requires_documented_leadership_exception(db):
    plan = _complete_draft(db, "FIN-UAT-003", target="40")
    submit_finance_plan(db, plan.plan_id, _user("project-manager"))
    finance_approve_plan(
        db,
        plan.plan_id,
        _user("finance"),
        note="A számítás helyes, a céltól való eltérés valós.",
    )
    with pytest.raises(ValueError, match="kivételindoklás"):
        leadership_approve_plan(
            db,
            plan.plan_id,
            _user("managing-director"),
            note="Vezetői felülvizsgálat elvégezve.",
            margin_exception_reason="túl rövid",
        )
    approved = leadership_approve_plan(
        db,
        plan.plan_id,
        _user("managing-director"),
        note="Vezetői felülvizsgálat elvégezve.",
        margin_exception_reason=(
            "Stratégiai referencia projekt; a csökkentett fedezet egyszeri és jóváhagyott."
        ),
    )
    assert approved.status == "approved"
    assert approved.margin_exception_reason.startswith("Stratégiai")


def test_finance_can_reject_review_with_reason_and_new_version_can_start(db):
    plan = _complete_draft(db, "FIN-UAT-004")
    submit_finance_plan(db, plan.plan_id, _user("project-manager"))
    with pytest.raises(ValueError, match="15 karakteres"):
        reject_finance_plan(db, plan.plan_id, _user("finance"), reason="rövid")
    rejected = reject_finance_plan(
        db,
        plan.plan_id,
        _user("finance"),
        reason="A költségforrások további dokumentálást igényelnek.",
    )
    assert rejected.status == "rejected"
    clone = clone_finance_plan(db, plan.plan_id, _user("project-manager"))
    assert clone.version == 2
    assert clone.status == "draft"


def test_finance_approval_enforces_three_distinct_people(db):
    plan = _complete_draft(db, "FIN-UAT-SOD")
    submit_finance_plan(db, plan.plan_id, _user("owner"))

    with pytest.raises(PermissionError, match="saját tervét"):
        finance_approve_plan(
            db,
            plan.plan_id,
            _user("owner"),
            note="A saját terv tiltott pénzügyi jóváhagyási kísérlete.",
        )

    finance_approve_plan(
        db,
        plan.plan_id,
        _user("finance"),
        note="A független pénzügyi ellenőrzés dokumentáltan megtörtént.",
    )
    with pytest.raises(PermissionError, match="benyújtója"):
        leadership_approve_plan(
            db,
            plan.plan_id,
            _user("owner"),
            note="Tiltott önjóváhagyási kísérlet a vezetői kapun.",
            margin_exception_reason="",
        )

    approved = leadership_approve_plan(
        db,
        plan.plan_id,
        _user("managing-director"),
        note="A független vezetői jóváhagyás dokumentáltan megtörtént.",
        margin_exception_reason="",
    )
    assert approved.status == "approved"

    second_plan = _complete_draft(db, "FIN-UAT-SOD-2")
    submit_finance_plan(db, second_plan.plan_id, _user("project-manager"))
    finance_approve_plan(
        db,
        second_plan.plan_id,
        _user("owner"),
        note="Tulajdonosi szerepben végzett pénzügyi ellenőrzés.",
    )
    with pytest.raises(PermissionError, match="pénzügyi ellenőre"):
        leadership_approve_plan(
            db,
            second_plan.plan_id,
            _user("owner"),
            note="Tiltott második kötelező kapu ugyanazon személlyel.",
            margin_exception_reason="",
        )


def test_finance_plan_ui_and_role_gate(logged_in_client, client, db):
    _project(db, "FIN-UI-001")
    response = logged_in_client.get("/financial/plans")
    assert response.status_code == 200
    assert "Projektköltségvetés és forecast" in response.text

    client.post("/logout")
    login = client.post(
        "/login",
        data={"email": "project-manager@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/financial/plans").status_code == 200

    client.post("/logout")
    login = client.post(
        "/login",
        data={"email": "sales@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert client.get("/financial/plans").status_code == 403
