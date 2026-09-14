from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings, _is_placeholder
from app.process_cards.domain import RealRole
from scripts.staging_preflight import (
    check_catalog,
    check_database_and_migration,
    check_directus,
    check_google_live,
    check_redis,
    check_runtime_storage,
    check_service_account,
)


@dataclass(slots=True)
class ProductionReport:
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


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def check_production_configuration(settings: Settings, report: ProductionReport) -> None:
    errors = settings.validation_errors()
    if settings.app_env != "production":
        errors.append("APP_ENV must be production")
    report.add(
        "production_configuration",
        not errors,
        "Production configuration is valid" if not errors else "; ".join(errors),
    )


def check_role_model(settings: Settings, report: ProductionReport) -> None:
    role_tokens = settings.human_role_tokens()
    expected = set(RealRole)
    tokens = list(role_tokens.values())
    ok = set(role_tokens) == expected and len(tokens) == len(set(tokens)) == 5
    report.add(
        "five_role_authorization",
        ok,
        "Exactly five unique human role tokens are configured"
        if ok
        else "Human authorization must contain exactly the five real roles with unique tokens",
        configured_roles=sorted(role.value for role in role_tokens),
    )


def check_pinned_images(env_values: dict[str, str], report: ProductionReport) -> None:
    required = ["IMPERIAL_HUB_IMAGE", "DIRECTUS_IMAGE", "N8N_IMAGE", "MINIO_IMAGE", "MINIO_MC_IMAGE"]
    failures: list[str] = []
    for key in required:
        value = env_values.get(key, "")
        if _is_placeholder(value) or value.endswith(":latest") or ":" not in value:
            failures.append(key)
    report.add(
        "pinned_container_images",
        not failures,
        "All production images are pinned" if not failures else "Unpinned or placeholder images: " + ", ".join(failures),
    )


def check_compose(env_file: Path, report: ProductionReport, *, require_docker: bool) -> None:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.staging.yml",
        "-f",
        "docker-compose.production.yml",
        "config",
        "--quiet",
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
        report.add(
            "production_compose",
            result.returncode == 0,
            "Production Compose configuration is valid"
            if result.returncode == 0
            else (result.stderr or result.stdout).strip(),
            mode="docker_compose",
        )
    except FileNotFoundError:
        try:
            payloads = [
                yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
                for name in (
                    "docker-compose.yml",
                    "docker-compose.staging.yml",
                    "docker-compose.production.yml",
                )
            ]
            services = [set((payload or {}).get("services", {})) for payload in payloads]
            ok = all(services) and {"backup", "backup-verify", "restore-drill"} <= services[2]
            if require_docker:
                ok = False
            report.add(
                "production_compose",
                ok,
                "Compose YAML structure is valid; Docker CLI unavailable for interpolation"
                if ok
                else "Docker CLI is required for online production preflight",
                mode="yaml_fallback",
            )
        except Exception as exc:  # noqa: BLE001
            report.add("production_compose", False, f"Compose YAML validation failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        report.add("production_compose", False, f"Compose validation failed: {exc}")


def check_ops_scripts(report: ProductionReport) -> None:
    failures: list[str] = []
    for script in sorted((ROOT / "scripts" / "ops").glob("*.sh")):
        result = subprocess.run(["sh", "-n", str(script)], capture_output=True, text=True)
        if result.returncode:
            failures.append(f"{script.name}: {result.stderr.strip()}")
    report.add(
        "operations_scripts",
        not failures,
        "Backup and restore-drill scripts pass shell syntax validation"
        if not failures
        else "; ".join(failures),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Imperial Intelligence production preflight")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--require-directus-catalog", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    env_path = Path(args.env_file)
    settings = Settings(_env_file=env_path)
    report = ProductionReport()
    check_production_configuration(settings, report)
    check_role_model(settings, report)
    check_pinned_images(load_dotenv(env_path), report)
    check_catalog(settings, report)
    check_runtime_storage(settings, report)
    check_service_account(settings, report)
    check_ops_scripts(report)
    check_compose(env_path, report, require_docker=args.online)

    if args.online:
        check_database_and_migration(settings, report)
        check_redis(settings, report)
        check_directus(settings, report, args.require_directus_catalog)
        check_google_live(settings, report)

    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
