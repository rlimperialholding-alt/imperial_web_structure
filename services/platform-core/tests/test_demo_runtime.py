from __future__ import annotations

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
