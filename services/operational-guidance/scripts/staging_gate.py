from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class Step:
    name: str
    command: list[str] | None
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "ok": self.ok,
            "returncode": self.returncode,
            "stdout": self.stdout[-8000:],
            "stderr": self.stderr[-8000:],
            "metadata": self.metadata,
        }


def run_command(name: str, command: list[str], env: dict[str, str] | None = None) -> Step:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )
    return Step(name, command, result.returncode == 0, result.returncode, result.stdout, result.stderr)


def validate_compose() -> Step:
    try:
        base = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        staging = yaml.safe_load((ROOT / "docker-compose.staging.yml").read_text(encoding="utf-8"))
        production = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text(encoding="utf-8"))
        required = {"postgres", "redis", "migrate", "api", "worker", "beat", "directus", "n8n"}
        services = set((base or {}).get("services", {}))
        staging_services = set((staging or {}).get("services", {}))
        production_services = set((production or {}).get("services", {}))
        errors: list[str] = []
        if not required <= services:
            errors.append(f"Missing base services: {sorted(required - services)}")
        if not {"api", "worker", "beat", "postgres", "directus", "n8n"} <= staging_services:
            errors.append("Staging overlay is incomplete")
        if not {"api", "worker", "beat", "backup", "backup-verify", "restore-drill"} <= production_services:
            errors.append("Production overlay is incomplete")
        api_depends = (base.get("services", {}).get("api", {}).get("depends_on", {}))
        if "migrate" not in api_depends:
            errors.append("API does not depend on the migration service")
        ok = not errors
        return Step(
            "compose_validation",
            None,
            ok,
            0 if ok else 1,
            "Docker Compose YAML structure is valid" if ok else "",
            "; ".join(errors),
            {
                "base_services": sorted(services),
                "staging_services": sorted(staging_services),
                "production_services": sorted(production_services),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return Step("compose_validation", None, False, 1, "", str(exc))


def run_migration_cycle() -> Step:
    with tempfile.TemporaryDirectory(prefix="iip-migration-") as tmp:
        db_path = Path(tmp) / "migration.db"
        env = {"DATABASE_URL": f"sqlite:///{db_path}", "APP_ENV": "test"}
        commands = [
            ["alembic", "upgrade", "head"],
            ["alembic", "downgrade", "base"],
            ["alembic", "upgrade", "head"],
        ]
        outputs: list[str] = []
        errors: list[str] = []
        for command in commands:
            step = run_command("migration_cycle_part", command, env)
            outputs.append(step.stdout)
            errors.append(step.stderr)
            if not step.ok:
                return Step(
                    "migration_cycle",
                    command,
                    False,
                    step.returncode,
                    "\n".join(outputs),
                    "\n".join(errors),
                )
        return Step(
            "migration_cycle",
            None,
            True,
            0,
            "Alembic upgrade/downgrade/upgrade cycle succeeded",
            "\n".join(errors),
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the v0.8.1 staging release gate")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime" / "staging-gate")
    parser.add_argument("--env-file", default=None, help="Optional real staging env file")
    parser.add_argument("--online", action="store_true", help="Run live infrastructure preflight")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    steps: list[Step] = []
    steps.append(run_command("pytest", [sys.executable, "-m", "pytest", "-q"]))
    steps.append(run_command("compileall", [sys.executable, "-m", "compileall", "-q", "app", "scripts", "tests"]))
    steps.append(validate_compose())
    steps.append(run_migration_cycle())

    preflight_command = [sys.executable, "scripts/staging_preflight.py"]
    if args.env_file:
        preflight_command.extend(["--env-file", args.env_file])
    if args.online:
        preflight_command.extend(["--online", "--require-directus-catalog"])
    preflight_command.extend(["--output", str(output / "preflight.json")])
    steps.append(run_command("staging_preflight", preflight_command))

    artifact_output = output / "operational-guidance-artifacts"
    steps.append(
        run_command(
            "operational_guidance_99x99_qa",
            [sys.executable, "scripts/qa_operational_guidance.py", "--output", str(artifact_output)],
        )
    )

    payload = {
        "release": "0.8.1",
        "status": "PASS" if all(step.ok for step in steps) else "FAIL",
        "steps": [step.to_dict() for step in steps],
    }
    report_path = output / "staging-gate-report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
