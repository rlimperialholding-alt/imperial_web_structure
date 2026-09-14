from __future__ import annotations

import json
from pathlib import Path

from app.demo_runtime import DemoRuntime


def test_every_registered_module_has_a_record_and_a_test_action(tmp_path):
    runtime = DemoRuntime(runtime_path=tmp_path / "runtime.json")
    state = runtime.reset()

    assert len(state["modules"]) >= 45
    assert state["summary"]["registeredModules"] == state["summary"]["testableModules"]
    assert all(module["records"] for module in state["modules"])
    assert all(module["actions"] for module in state["modules"])
    assert len({module["id"] for module in state["modules"]}) == len(state["modules"])


def test_action_uses_project_correlation_idempotency_outbox_and_audit(tmp_path):
    runtime = DemoRuntime(runtime_path=tmp_path / "runtime.json")
    runtime.reset()

    first = runtime.execute_action(
        module_id="crm",
        action_id="qualify_lead",
        project_id="PRJ-DEMO-001",
        correlation_id="CORR-TEST-001",
        idempotency_key="IDEMP-TEST-001",
    )
    duplicate = runtime.execute_action(
        module_id="crm",
        action_id="qualify_lead",
        project_id="PRJ-DEMO-001",
        correlation_id="CORR-TEST-001",
        idempotency_key="IDEMP-TEST-001",
    )
    state = runtime.state()

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert first["event"]["projectId"] == "PRJ-DEMO-001"
    assert first["event"]["correlationId"] == "CORR-TEST-001"
    assert first["event"]["idempotencyKey"] == "IDEMP-TEST-001"
    assert len(state["events"]) == 1
    assert len(state["audit"]) == 1
    assert {item["consumer"] for item in state["outbox"]} == {
        "housematch",
        "booking-engine",
        "sales",
    }


def test_customer_and_marketing_journeys_cross_module_boundaries(tmp_path):
    runtime = DemoRuntime(runtime_path=tmp_path / "runtime.json")
    runtime.reset()

    customer = runtime.run_journey("customer-to-care")
    marketing = runtime.run_journey("campaign-to-profit")
    state = runtime.state()

    assert customer["journey"]["status"] == "completed"
    assert marketing["journey"]["status"] == "completed"
    assert len(customer["events"]) == len(customer["journey"]["steps"])
    assert len(marketing["events"]) == len(marketing["journey"]["steps"])
    assert len({event["correlationId"] for event in customer["events"]}) == 1
    assert len({event["correlationId"] for event in marketing["events"]}) == 1
    assert state["summary"]["journeys"]["customer-to-care"]["completedSteps"] == 20
    assert state["summary"]["journeys"]["campaign-to-profit"]["completedSteps"] == 11
    assert state["summary"]["outbox"]["retry"] == 0


def test_failure_retry_and_reset_are_visible(tmp_path):
    runtime = DemoRuntime(runtime_path=tmp_path / "runtime.json")
    runtime.reset()
    runtime.execute_action(
        module_id="crm",
        action_id="qualify_lead",
        project_id="PRJ-DEMO-001",
    )

    failed = runtime.inject_failure("housematch")
    failed_snapshot = dict(failed)
    retried = runtime.retry_outbox(failed["id"])
    reset = runtime.reset()

    assert failed_snapshot["status"] == "retry"
    assert retried["status"] == "delivered"
    assert reset["events"] == []
    assert reset["outbox"] == []


def test_demo_seed_module_set_matches_registered_portal_modules() -> None:
    """A demó seed modulhalmaza pontosan a regisztrált portal modulhalmaz.

    Task59 regresszió: a seed a ``house-designer`` és a
    ``market-creative-intelligence`` modult deklarálta anélkül, hogy a
    portal/route/runtime deklarációk is tartalmazták volna őket. A két
    modul most már explicit: portal route, platform-admin hozzáférés és
    client routeMap egyaránt létezik, és ez a teszt a halmaz-egyenlőséget
    zárolja, hogy a jövőbeni eltérés a lokális pytest futtatásban is
    azonnal látszódjon (nem csak a CI validatorban).
    """
    root = Path(__file__).resolve().parents[3]
    portal = json.loads(
        (root / "sites" / "_portal" / "data" / "platform.json").read_text(encoding="utf-8")
    )
    seed = json.loads(
        (
            root / "services" / "platform-core" / "data" / "platform_demo_seed.json"
        ).read_text(encoding="utf-8")
    )
    portal_ids = {module["id"] for module in portal["modules"]}
    seed_ids = {module["id"] for module in seed["modules"]}
    assert seed_ids == portal_ids
    assert {"house-designer", "market-creative-intelligence"} <= portal_ids
    for module in portal["modules"]:
        assert module["route"] == f"/{module['id']}/"
