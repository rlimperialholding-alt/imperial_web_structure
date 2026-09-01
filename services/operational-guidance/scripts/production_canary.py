from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx

from app.config import Settings
from app.process_cards.domain import RealRole


@dataclass(slots=True)
class CanaryReport:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, **metadata: Any) -> None:
        self.checks.append({"name": name, "ok": ok, "detail": detail, **metadata})

    @property
    def passed(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "checks": self.checks,
            "failed": [item for item in self.checks if not item["ok"]],
        }


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def expect(
    report: CanaryReport,
    response: httpx.Response,
    name: str,
    expected: set[int] | int,
) -> Any:
    expected_set = {expected} if isinstance(expected, int) else expected
    ok = response.status_code in expected_set
    detail = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        payload = response.text[:500]
    report.add(name, ok, detail, response=payload if not ok else None)
    if not ok:
        raise RuntimeError(f"{name} failed: HTTP {response.status_code}: {payload}")
    return payload


def run_canary(base_url: str, settings: Settings, process_key: str) -> CanaryReport:
    report = CanaryReport()
    role_tokens = settings.human_role_tokens()
    manager_token = role_tokens.get(RealRole.UGYVEZETO)
    if not manager_token:
        report.add("manager_token", False, "Ügyvezető token is missing")
        return report
    run_id = f"CANARY-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    timeout = httpx.Timeout(30.0, connect=10.0)
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        expect(report, client.get("/live"), "liveness", 200)
        ready = expect(report, client.get("/ready"), "readiness", 200)
        report.add("readiness_status", ready.get("status") == "ready", str(ready.get("status")))
        expect(
            report,
            client.get("/api/v1/checklists/templates"),
            "unauthenticated_request_rejected",
            401,
        )
        manager_headers = bearer(manager_token)
        expect(
            report,
            client.post("/api/v1/process-cards/catalog/import", headers=manager_headers),
            "catalog_import",
            200,
        )
        generated = expect(
            report,
            client.post(
                f"/api/v1/process-cards/{process_key}/generate",
                headers=manager_headers,
            ),
            "process_card_generate",
            200,
        )
        card = generated["card"]
        version = int(card["version"])
        approved = expect(
            report,
            client.post(
                f"/api/v1/process-cards/{process_key}/versions/{version}/approve",
                headers=manager_headers,
                json={},
            ),
            "manager_approval",
            200,
        )
        report.add(
            "process_card_approved",
            approved["card"]["status"] == "approved",
            approved["card"]["status"],
        )

        role = RealRole(card["role"])
        role_token = role_tokens.get(role)
        if not role_token:
            raise RuntimeError(f"Missing token for role {role.value}")
        role_headers = bearer(role_token)
        role_headers["X-Idempotency-Key"] = f"{run_id}-PASS"
        start_payload = {
            "process_key": process_key,
            "object_id": f"{run_id}-PASS",
            "object_type": "CanaryObject",
            "metadata": {"canary": True, "run_id": run_id},
        }
        instance = expect(
            report,
            client.post("/api/v1/checklists/instances", headers=role_headers, json=start_payload),
            "checklist_start",
            200,
        )
        repeated = expect(
            report,
            client.post("/api/v1/checklists/instances", headers=role_headers, json=start_payload),
            "checklist_start_idempotent_retry",
            200,
        )
        report.add(
            "idempotency_same_instance",
            instance["instance_id"] == repeated["instance_id"],
            repeated["instance_id"],
        )
        instance_id = instance["instance_id"]
        evidence = [f"EVID-{run_id}"]
        for item in instance["items"]:
            expect(
                report,
                client.put(
                    f"/api/v1/checklists/instances/{instance_id}/items/{item['item_id']}",
                    headers=role_headers,
                    json={"answer": "IGEN", "evidence_ids": evidence},
                ),
                f"answer_{item['item_id']}",
                200,
            )
        expect(
            report,
            client.post(
                f"/api/v1/checklists/instances/{instance_id}/evidence",
                headers=role_headers,
                json={"evidence_ids": evidence},
            ),
            "checklist_evidence",
            200,
        )
        expect(
            report,
            client.post(
                f"/api/v1/checklists/instances/{instance_id}/submit",
                headers=role_headers,
                json={},
            ),
            "checklist_submit",
            200,
        )
        expect(
            report,
            client.post(
                f"/api/v1/checklists/instances/{instance_id}/approve",
                headers=manager_headers,
                json={},
            ),
            "checklist_manager_approval",
            200,
        )
        gate = expect(
            report,
            client.get(
                f"/api/v1/checklists/instances/{instance_id}/gate",
                headers=role_headers,
            ),
            "closed_gate_read",
            200,
        )
        report.add("closed_gate_can_proceed", gate.get("can_proceed") is True, str(gate))

        hold_headers = bearer(role_token)
        hold_headers["X-Idempotency-Key"] = f"{run_id}-HOLD"
        hold_instance = expect(
            report,
            client.post(
                "/api/v1/checklists/instances",
                headers=hold_headers,
                json=start_payload | {"object_id": f"{run_id}-HOLD"},
            ),
            "hold_checklist_start",
            200,
        )
        blocking = next(item for item in hold_instance["items"] if item["blocking"])
        held = expect(
            report,
            client.put(
                f"/api/v1/checklists/instances/{hold_instance['instance_id']}/items/{blocking['item_id']}",
                headers=hold_headers,
                json={
                    "answer": "NEM",
                    "note": "Automatikus production canary HOLD-próba.",
                    "action_owner_role": role.value,
                    "action_due_date": (date.today() + timedelta(days=1)).isoformat(),
                },
            ),
            "blocking_no_answer",
            200,
        )
        report.add("blocking_no_sets_hold", held.get("status") == "hold", held.get("status"))
        hold_gate = expect(
            report,
            client.get(
                f"/api/v1/checklists/instances/{hold_instance['instance_id']}/gate",
                headers=hold_headers,
            ),
            "hold_gate_read",
            200,
        )
        report.add(
            "hold_gate_blocks_progress",
            hold_gate.get("can_proceed") is False and hold_gate.get("status") == "hold",
            str(hold_gate),
        )
        expect(
            report,
            client.get("/api/v1/operations/status", headers=manager_headers),
            "operations_status",
            200,
        )
        metrics_headers = {"X-Metrics-Token": settings.metrics_token.get_secret_value()}
        metrics = client.get("/metrics", headers=metrics_headers)
        report.add(
            "metrics_endpoint",
            metrics.status_code == 200 and "imperial_http_requests_total" in metrics.text,
            f"HTTP {metrics.status_code}",
        )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Imperial production canary UAT")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--process-key", default="SAL-001")
    parser.add_argument("--output", default="runtime/production-canary.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings(_env_file=args.env_file)
    report = run_canary(args.base_url, settings, args.process_key)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
