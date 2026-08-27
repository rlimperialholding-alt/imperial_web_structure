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
class UATReport:
    run_id: str
    environment: str
    base_url: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    pilots: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, **metadata: Any) -> None:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail, **metadata})

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(item["ok"] for item in self.checks)

    def to_dict(self) -> dict[str, Any]:
        failed = [item for item in self.checks if not item["ok"]]
        return {
            "status": "GO" if self.passed else "NO-GO",
            "run_id": self.run_id,
            "environment": self.environment,
            "base_url": self.base_url,
            "check_count": len(self.checks),
            "failed_count": len(failed),
            "checks": self.checks,
            "pilots": self.pilots,
            "failed": failed,
        }


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Request-ID": str(uuid.uuid4())}


def response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return response.text[:1000]


def expect(report: UATReport, name: str, response: httpx.Response, expected: int | set[int]) -> Any:
    expected_set = {expected} if isinstance(expected, int) else expected
    payload = response_payload(response)
    ok = response.status_code in expected_set
    report.add(name, ok, f"HTTP {response.status_code}", response=None if ok else payload)
    if not ok:
        raise RuntimeError(f"{name}: HTTP {response.status_code}: {payload}")
    return payload


def google_services(settings: Settings):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    source = settings.resolved_path(settings.google_service_account_file)
    drive_creds = service_account.Credentials.from_service_account_file(
        source, scopes=["https://www.googleapis.com/auth/drive"]
    )
    gmail_creds = service_account.Credentials.from_service_account_file(
        source,
        scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
    ).with_subject(settings.process_card_gmail_delegated_user)
    return (
        build("drive", "v3", credentials=drive_creds, cache_discovery=False),
        build("gmail", "v1", credentials=gmail_creds, cache_discovery=False),
    )


def escape_drive(value: str) -> str:
    return value.replace("'", "\\'")


def drive_child(drive, parent_id: str, name: str, folder: bool | None = None) -> dict[str, Any] | None:
    clauses = [f"name='{escape_drive(name)}'", f"'{parent_id}' in parents", "trashed=false"]
    if folder is True:
        clauses.append("mimeType='application/vnd.google-apps.folder'")
    elif folder is False:
        clauses.append("mimeType!='application/vnd.google-apps.folder'")
    result = drive.files().list(
        q=" and ".join(clauses),
        fields="files(id,name,mimeType,webViewLink,modifiedTime,size)",
        pageSize=20,
    ).execute()
    files = result.get("files", [])
    return files[0] if files else None


def drive_path(drive, root_id: str, parts: list[str]) -> dict[str, Any] | None:
    current: dict[str, Any] = {"id": root_id, "name": "root"}
    for part in parts:
        found = drive_child(drive, current["id"], part, folder=True)
        if not found:
            return None
        current = found
    return current


def list_drive_files(drive, folder_id: str) -> list[dict[str, Any]]:
    result = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id,name,mimeType,webViewLink,size,modifiedTime)",
        pageSize=100,
    ).execute()
    return result.get("files", [])


def check_directus(settings: Settings, report: UATReport) -> None:
    token = settings.directus_static_token.get_secret_value().strip()
    headers = {"Authorization": f"Bearer {token}"}
    counts: dict[str, int] = {}
    for label, collection in {
        "processes": settings.process_catalog_collection,
        "checklists": settings.checklist_template_collection,
    }.items():
        response = httpx.get(
            f"{settings.directus_url.rstrip('/')}/items/{collection}",
            headers=headers,
            params={"aggregate[count]": "*", "limit": 0},
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json().get("data", [])
        counts[label] = int(rows[0].get("count", 0)) if rows else 0
    report.add(
        "directus_catalog_99_99",
        counts == {"processes": 99, "checklists": 99},
        str(counts),
        **counts,
    )


def check_gmail_sent(gmail, process_key: str, version: int) -> tuple[bool, str]:
    subject = f"Process Card jóváhagyás: {process_key} v{version}"
    result = gmail.users().messages().list(
        userId="me", q=f'in:sent subject:"{subject}" newer_than:2d', maxResults=10
    ).execute()
    messages = result.get("messages", [])
    return bool(messages), messages[0]["id"] if messages else "not-found"


def run_pilot(
    client: httpx.Client,
    settings: Settings,
    report: UATReport,
    process_key: str,
    drive,
    gmail,
) -> None:
    role_tokens = settings.human_role_tokens()
    manager_token = role_tokens[RealRole.UGYVEZETO]
    generated = expect(
        report,
        f"{process_key}.generate",
        client.post(
            f"/api/v1/process-cards/{process_key}/generate?force=true",
            headers=bearer(manager_token),
        ),
        200,
    )
    card = generated["card"]
    version = int(card["version"])
    role = RealRole(card["role"])
    role_token = role_tokens[role]
    notification_id = str(generated.get("notification_id", ""))
    report.add(
        f"{process_key}.gmail_send_result",
        settings.gmail_approval_enabled
        and bool(notification_id)
        and not notification_id.startswith(("notification-failed", "notifier-disabled")),
        notification_id,
    )

    draft_folder = drive_path(
        drive,
        settings.process_card_drive_folder_id,
        ["00_JÓVÁHAGYÁSRA_VÁR", role.value, process_key, f"v{version:03d}"],
    )
    draft_files = list_drive_files(drive, draft_folder["id"]) if draft_folder else []
    draft_names = {item["name"] for item in draft_files}
    report.add(
        f"{process_key}.drive_draft",
        draft_folder is not None
        and any(name.lower().endswith(".pdf") for name in draft_names)
        and any(name.lower().endswith(".png") for name in draft_names),
        f"folder={bool(draft_folder)}, files={sorted(draft_names)}",
    )

    gmail_ok, gmail_id = check_gmail_sent(gmail, process_key, version)
    report.add(f"{process_key}.gmail_sent_visible", gmail_ok, gmail_id)

    service_tokens = settings.service_tokens()
    service_token = next(iter(service_tokens.values()))
    expect(
        report,
        f"{process_key}.service_cannot_approve",
        client.post(
            f"/api/v1/process-cards/{process_key}/versions/{version}/approve",
            headers=bearer(service_token),
            json={},
        ),
        403,
    )

    non_manager_role = next(item for item in RealRole if item != RealRole.UGYVEZETO)
    expect(
        report,
        f"{process_key}.employee_cannot_approve",
        client.post(
            f"/api/v1/process-cards/{process_key}/versions/{version}/approve",
            headers=bearer(role_tokens[non_manager_role]),
            json={},
        ),
        403,
    )

    approved = expect(
        report,
        f"{process_key}.manager_approval",
        client.post(
            f"/api/v1/process-cards/{process_key}/versions/{version}/approve",
            headers=bearer(manager_token),
            json={},
        ),
        200,
    )
    report.add(
        f"{process_key}.approved_status",
        approved.get("card", {}).get("status") == "approved",
        str(approved.get("card", {}).get("status")),
    )

    approved_folder = drive_path(
        drive,
        settings.process_card_drive_folder_id,
        ["01_ÉRVÉNYES", role.value, process_key, f"v{version:03d}"],
    )
    approved_files = list_drive_files(drive, approved_folder["id"]) if approved_folder else []
    report.add(
        f"{process_key}.drive_approved",
        approved_folder is not None and len(approved_files) >= 2,
        f"folder={bool(approved_folder)}, files={[item['name'] for item in approved_files]}",
    )

    object_base = f"{report.run_id}-{process_key}"
    start_headers = bearer(role_token)
    start_headers["X-Idempotency-Key"] = f"{object_base}-PASS"
    start_payload = {
        "process_key": process_key,
        "object_id": f"{object_base}-PASS",
        "object_type": "OnlineUAT",
        "metadata": {"uat": True, "run_id": report.run_id, "pilot": process_key},
    }
    instance = expect(
        report,
        f"{process_key}.checklist_start",
        client.post("/api/v1/checklists/instances", headers=start_headers, json=start_payload),
        200,
    )
    repeated = expect(
        report,
        f"{process_key}.idempotent_retry",
        client.post("/api/v1/checklists/instances", headers=start_headers, json=start_payload),
        200,
    )
    report.add(
        f"{process_key}.idempotent_same_instance",
        instance["instance_id"] == repeated["instance_id"],
        repeated["instance_id"],
    )
    instance_id = instance["instance_id"]
    evidence = [f"EVID-{object_base}"]
    for item in instance["items"]:
        expect(
            report,
            f"{process_key}.answer.{item['item_id']}",
            client.put(
                f"/api/v1/checklists/instances/{instance_id}/items/{item['item_id']}",
                headers=bearer(role_token),
                json={"answer": "IGEN", "evidence_ids": evidence},
            ),
            200,
        )
    expect(
        report,
        f"{process_key}.evidence",
        client.post(
            f"/api/v1/checklists/instances/{instance_id}/evidence",
            headers=bearer(role_token),
            json={"evidence_ids": evidence},
        ),
        200,
    )
    expect(
        report,
        f"{process_key}.submit",
        client.post(
            f"/api/v1/checklists/instances/{instance_id}/submit",
            headers=bearer(role_token),
            json={},
        ),
        200,
    )
    expect(
        report,
        f"{process_key}.checklist_approval",
        client.post(
            f"/api/v1/checklists/instances/{instance_id}/approve",
            headers=bearer(manager_token),
            json={},
        ),
        200,
    )
    gate = expect(
        report,
        f"{process_key}.closed_gate",
        client.get(
            f"/api/v1/checklists/instances/{instance_id}/gate", headers=bearer(role_token)
        ),
        200,
    )
    report.add(
        f"{process_key}.closed_can_proceed",
        gate.get("can_proceed") is True and gate.get("status") == "closed",
        str(gate),
    )

    hold_headers = bearer(role_token)
    hold_headers["X-Idempotency-Key"] = f"{object_base}-HOLD"
    hold = expect(
        report,
        f"{process_key}.hold_start",
        client.post(
            "/api/v1/checklists/instances",
            headers=hold_headers,
            json=start_payload | {"object_id": f"{object_base}-HOLD"},
        ),
        200,
    )
    blocking = next(item for item in hold["items"] if item["blocking"])
    held = expect(
        report,
        f"{process_key}.blocking_no",
        client.put(
            f"/api/v1/checklists/instances/{hold['instance_id']}/items/{blocking['item_id']}",
            headers=bearer(role_token),
            json={
                "answer": "NEM",
                "note": "Online staging UAT HOLD-próba.",
                "action_owner_role": role.value,
                "action_due_date": (date.today() + timedelta(days=1)).isoformat(),
            },
        ),
        200,
    )
    hold_gate = expect(
        report,
        f"{process_key}.hold_gate",
        client.get(
            f"/api/v1/checklists/instances/{hold['instance_id']}/gate",
            headers=bearer(role_token),
        ),
        200,
    )
    report.add(
        f"{process_key}.hold_blocks",
        held.get("status") == "hold"
        and hold_gate.get("status") == "hold"
        and hold_gate.get("can_proceed") is False,
        str(hold_gate),
    )
    report.pilots.append(
        {
            "process_key": process_key,
            "role": role.value,
            "version": version,
            "notification_id": notification_id,
            "pass_instance_id": instance_id,
            "hold_instance_id": hold["instance_id"],
        }
    )


def run(base_url: str, settings: Settings, processes: list[str]) -> UATReport:
    report = UATReport(
        run_id=f"UAT-{int(time.time())}-{uuid.uuid4().hex[:8]}",
        environment=settings.app_env,
        base_url=base_url.rstrip("/"),
    )
    errors = settings.validation_errors()
    report.add("configuration", not errors, "valid" if not errors else "; ".join(errors))
    if errors:
        return report
    role_tokens = settings.human_role_tokens()
    report.add("five_roles", set(role_tokens) == set(RealRole), ", ".join(role.value for role in role_tokens))
    drive, gmail = google_services(settings)
    timeout = httpx.Timeout(45.0, connect=10.0)
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as client:
        expect(report, "liveness", client.get("/live"), 200)
        ready = expect(report, "readiness", client.get("/ready"), 200)
        report.add("ready_state", ready.get("status") == "ready", str(ready.get("status")))
        expect(report, "unauthenticated_rejected", client.get("/api/v1/checklists/templates"), 401)
        for role, token in role_tokens.items():
            templates = expect(
                report,
                f"role_access.{role.value}",
                client.get("/api/v1/checklists/templates", headers=bearer(token)),
                200,
            )
            report.add(f"role_access.{role.value}.templates_99", len(templates) == 99, str(len(templates)))
        manager = role_tokens[RealRole.UGYVEZETO]
        imported = expect(
            report,
            "catalog_import",
            client.post("/api/v1/process-cards/catalog/import", headers=bearer(manager)),
            200,
        )
        report.add(
            "api_catalog_99_99",
            imported.get("total_processes") == 99 and imported.get("total_checklists") == 99,
            str(imported),
        )
        check_directus(settings, report)
        for process_key in processes:
            try:
                run_pilot(client, settings, report, process_key, drive, gmail)
            except Exception as exc:  # noqa: BLE001
                report.add(f"{process_key}.pilot_exception", False, f"{type(exc).__name__}: {exc}")
        expect(
            report,
            "operations_status",
            client.get("/api/v1/operations/status", headers=bearer(manager)),
            200,
        )
        metrics = client.get(
            "/metrics",
            headers={"X-Metrics-Token": settings.metrics_token.get_secret_value()},
        )
        report.add(
            "metrics",
            metrics.status_code == 200 and "imperial_http_requests_total" in metrics.text,
            f"HTTP {metrics.status_code}",
        )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run complete online staging UAT")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--processes", default="SAL-001,PRJ-001,FIN-001", help="Comma-separated ProcessID list"
    )
    parser.add_argument("--output", default="runtime/uat/online-staging-uat-v0.8.1.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = Settings(_env_file=args.env_file)
    processes = [item.strip() for item in args.processes.split(",") if item.strip()]
    report = run(args.base_url, settings, processes)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
