from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings


@dataclass(slots=True)
class ReadinessReport:
    ready: bool = True
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str, **metadata: Any) -> None:
        self.checks[name] = {"ok": ok, "detail": detail, **metadata}
        if not ok:
            self.ready = False

    def to_dict(self) -> dict[str, Any]:
        return {"status": "ready" if self.ready else "not_ready", "checks": self.checks}


def _check_catalog(settings: Settings, report: ReadinessReport) -> None:
    if not settings.operational_guidance_enabled:
        report.add("operational_catalog", True, "Operational Guidance Engine disabled")
        return

    path = settings.resolved_path(settings.operational_catalog_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        processes = payload.get("processes", [])
        templates = payload.get("checklist_templates", [])
        process_ids = {item.get("process_key") for item in processes}
        template_process_ids = {item.get("process_key") for item in templates}
        ok = (
            len(processes) == 99
            and len(templates) == 99
            and len(process_ids) == 99
            and process_ids == template_process_ids
        )
        detail = (
            f"{len(processes)} processes and {len(templates)} checklist templates loaded"
            if ok
            else "Catalog must contain 99 unique processes linked to 99 checklist templates"
        )
        report.add(
            "operational_catalog",
            ok,
            detail,
            path=str(path),
            process_count=len(processes),
            checklist_count=len(templates),
        )
    except Exception as exc:  # noqa: BLE001 - readiness must report every failure
        report.add("operational_catalog", False, f"Catalog read failed: {exc}", path=str(path))


def _check_runtime_directories(settings: Settings, report: ReadinessReport) -> None:
    failures: list[str] = []
    checked: list[str] = []
    for path in settings.runtime_directories():
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path, prefix=".readiness-", delete=False) as handle:
                handle.write(b"ok")
                probe = Path(handle.name)
            probe.unlink(missing_ok=True)
            checked.append(str(path))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path}: {exc}")
    report.add(
        "runtime_storage",
        not failures,
        "Runtime directories are writable" if not failures else "; ".join(failures),
        directories=checked,
        uid=os.getuid() if hasattr(os, "getuid") else None,
    )


def build_readiness_report(db: Session, settings: Settings) -> ReadinessReport:
    report = ReadinessReport()

    config_errors = settings.validation_errors() if settings.startup_validate_config else []
    report.add(
        "configuration",
        not config_errors,
        "Runtime configuration is valid" if not config_errors else "; ".join(config_errors),
        environment=settings.app_env,
    )

    try:
        db.execute(text("SELECT 1"))
        report.add("database", True, "Database query succeeded")
    except Exception as exc:  # noqa: BLE001
        report.add("database", False, f"Database query failed: {exc}")

    if settings.readiness_check_redis:
        try:
            from redis import Redis

            client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
            report.add("redis", bool(client.ping()), "Redis ping succeeded")
        except Exception as exc:  # noqa: BLE001
            report.add("redis", False, f"Redis ping failed: {exc}")
    else:
        report.add("redis", True, "Redis readiness check disabled")

    _check_catalog(settings, report)
    _check_runtime_directories(settings, report)
    return report
