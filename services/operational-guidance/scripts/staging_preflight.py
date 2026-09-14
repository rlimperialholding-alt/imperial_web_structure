from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.config import Settings


@dataclass(slots=True)
class GateReport:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str, **metadata: Any) -> None:
        self.checks.append({"name": name, "ok": ok, "detail": detail, **metadata})

    @property
    def passed(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "check_count": len(self.checks),
            "failed_count": sum(not item["ok"] for item in self.checks),
            "checks": self.checks,
        }


def load_settings(env_file: str | None) -> Settings:
    kwargs: dict[str, Any] = {}
    if env_file:
        kwargs["_env_file"] = env_file
    return Settings(**kwargs)


def check_configuration(settings: Settings, report: GateReport) -> None:
    errors = settings.validation_errors()
    report.add(
        "configuration",
        not errors,
        "Configuration is valid" if not errors else "; ".join(errors),
        environment=settings.app_env,
    )


def check_catalog(settings: Settings, report: GateReport) -> None:
    path = settings.resolved_path(settings.operational_catalog_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        processes = payload.get("processes", [])
        templates = payload.get("checklist_templates", [])
        process_ids = {item.get("process_key") for item in processes}
        template_map = {item.get("process_key"): item for item in templates}
        linked = all(
            process.get("checklist_template_id")
            == template_map.get(process.get("process_key"), {}).get("template_id")
            and process.get("gate_id")
            == template_map.get(process.get("process_key"), {}).get("gate_id")
            for process in processes
        )
        roles = set(payload.get("real_roles", []))
        expected_roles = {"Ügyvezető", "Marketinges", "Értékesítő", "Pénzügyes", "Projektmenedzser"}
        ok = (
            len(processes) == 99
            and len(templates) == 99
            and len(process_ids) == 99
            and len(template_map) == 99
            and linked
            and roles == expected_roles
        )
        report.add(
            "operational_catalog",
            ok,
            "99/99 Process Card and checklist mapping is consistent"
            if ok
            else "Operational catalog integrity check failed",
            path=str(path),
            processes=len(processes),
            templates=len(templates),
            roles=sorted(roles),
        )
    except Exception as exc:  # noqa: BLE001
        report.add("operational_catalog", False, f"Catalog check failed: {exc}", path=str(path))


def check_runtime_storage(settings: Settings, report: GateReport) -> None:
    failures: list[str] = []
    paths: list[str] = []
    for path in settings.runtime_directories():
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, prefix=".preflight-", delete=False) as handle:
                handle.write(b"ok")
                probe = Path(handle.name)
            probe.unlink(missing_ok=True)
            paths.append(str(path))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path}: {exc}")
    report.add(
        "runtime_storage",
        not failures,
        "Runtime storage is writable" if not failures else "; ".join(failures),
        paths=paths,
    )


def check_service_account(settings: Settings, report: GateReport) -> None:
    if not (settings.drive_publication_enabled or settings.gmail_approval_enabled):
        report.add("google_service_account", True, "Google publication features are disabled")
        return
    path = settings.resolved_path(settings.google_service_account_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"type", "client_email", "private_key", "token_uri"}
        missing = sorted(required - payload.keys())
        ok = payload.get("type") == "service_account" and not missing
        report.add(
            "google_service_account",
            ok,
            "Service-account JSON structure is valid"
            if ok
            else f"Missing or invalid fields: {', '.join(missing) or 'type'}",
            path=str(path),
            client_email=payload.get("client_email"),
        )
    except Exception as exc:  # noqa: BLE001
        report.add("google_service_account", False, f"Service-account check failed: {exc}")


def check_database_and_migration(settings: Settings, report: GateReport) -> None:
    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        config = Config(str(Path.cwd() / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        report.add(
            "database",
            True,
            "Database connection succeeded",
        )
        report.add(
            "database_migration",
            current == head,
            "Database is at Alembic head" if current == head else "Database migration is not current",
            current=current,
            expected=head,
        )
    except Exception as exc:  # noqa: BLE001
        report.add("database", False, f"Database or migration check failed: {exc}")


def check_redis(settings: Settings, report: GateReport) -> None:
    try:
        from redis import Redis

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
        ok = bool(client.ping())
        report.add("redis", ok, "Redis ping succeeded" if ok else "Redis ping returned false")
    except Exception as exc:  # noqa: BLE001
        report.add("redis", False, f"Redis check failed: {exc}")


def check_directus(settings: Settings, report: GateReport, require_loaded_catalog: bool) -> None:
    headers = {}
    token = settings.directus_static_token.get_secret_value().strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(f"{settings.directus_url.rstrip('/')}/server/health", timeout=10)
        response.raise_for_status()
        report.add("directus_health", True, "Directus health endpoint succeeded")
        if require_loaded_catalog:
            if not token:
                report.add("directus_catalog", False, "DIRECTUS_STATIC_TOKEN is required")
                return
            counts: dict[str, int] = {}
            for name, collection in {
                "processes": settings.process_catalog_collection,
                "checklists": settings.checklist_template_collection,
            }.items():
                result = httpx.get(
                    f"{settings.directus_url.rstrip('/')}/items/{collection}",
                    headers=headers,
                    params={"aggregate[count]": "*", "limit": 0},
                    timeout=15,
                )
                result.raise_for_status()
                data = result.json().get("data", [])
                count = int(data[0].get("count", 0)) if data else 0
                counts[name] = count
            ok = counts == {"processes": 99, "checklists": 99}
            report.add(
                "directus_catalog",
                ok,
                "Directus contains the complete 99/99 catalog"
                if ok
                else "Directus catalog counts do not match 99/99",
                **counts,
            )
    except Exception as exc:  # noqa: BLE001
        report.add("directus_health", False, f"Directus check failed: {exc}")


def check_google_live(settings: Settings, report: GateReport) -> None:
    if not settings.drive_publication_enabled:
        report.add("google_drive", True, "Drive publication is disabled")
        return
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        path = settings.resolved_path(settings.google_service_account_file)
        drive_creds = service_account.Credentials.from_service_account_file(
            path, scopes=["https://www.googleapis.com/auth/drive"]
        )
        drive = build("drive", "v3", credentials=drive_creds, cache_discovery=False)
        folder = drive.files().get(
            fileId=settings.process_card_drive_folder_id,
            fields="id,name,mimeType,capabilities(canAddChildren)",
        ).execute()
        ok = (
            folder.get("mimeType") == "application/vnd.google-apps.folder"
            and folder.get("capabilities", {}).get("canAddChildren") is True
        )
        report.add(
            "google_drive",
            ok,
            "Target Drive folder is writable" if ok else "Target Drive folder is not writable",
            folder_id=folder.get("id"),
            folder_name=folder.get("name"),
        )
    except Exception as exc:  # noqa: BLE001
        report.add("google_drive", False, f"Drive check failed: {exc}")

    if not settings.gmail_approval_enabled:
        report.add("gmail_delegation", True, "Gmail approval is disabled")
        return
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        path = settings.resolved_path(settings.google_service_account_file)
        gmail_creds = service_account.Credentials.from_service_account_file(
            path, scopes=["https://www.googleapis.com/auth/gmail.send"]
        ).with_subject(settings.process_card_gmail_delegated_user)
        gmail = build("gmail", "v1", credentials=gmail_creds, cache_discovery=False)
        profile = gmail.users().getProfile(userId="me").execute()
        ok = profile.get("emailAddress", "").lower() == settings.process_card_gmail_delegated_user.lower()
        report.add(
            "gmail_delegation",
            ok,
            "Domain-wide delegation is available" if ok else "Delegated Gmail identity mismatch",
            delegated_user=profile.get("emailAddress"),
        )
    except Exception as exc:  # noqa: BLE001
        report.add("gmail_delegation", False, f"Gmail delegation check failed: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Imperial Intelligence staging preflight gate")
    parser.add_argument("--env-file", default=None, help="Environment file to validate")
    parser.add_argument("--online", action="store_true", help="Check live infrastructure and APIs")
    parser.add_argument(
        "--require-directus-catalog",
        action="store_true",
        help="Require 99/99 records in the live Directus collections",
    )
    parser.add_argument("--output", default=None, help="Write JSON report to this path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings(args.env_file)
    report = GateReport()
    check_configuration(settings, report)
    check_catalog(settings, report)
    check_runtime_storage(settings, report)
    check_service_account(settings, report)

    if args.online:
        check_database_and_migration(settings, report)
        check_redis(settings, report)
        check_directus(settings, report, args.require_directus_catalog)
        check_google_live(settings, report)

    payload = report.to_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
