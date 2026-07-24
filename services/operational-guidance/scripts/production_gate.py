from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class Gate:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def run(self, name: str, command: list[str], timeout: int = 300) -> None:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        self.checks.append(
            {
                "name": name,
                "ok": result.returncode == 0,
                "command": command,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            }
        )

    @property
    def passed(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def payload(self) -> dict[str, Any]:
        return {
            "status": "PASS" if self.passed else "FAIL",
            "check_count": len(self.checks),
            "failed_count": sum(not item["ok"] for item in self.checks),
            "checks": self.checks,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Imperial v0.8.1 production release gate")
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--staging-report", default=None, help="Reuse a previously completed PASS staging gate report")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--output", default="runtime/production-gate-v0.8.1.json")
    args = parser.parse_args()

    gate = Gate()
    gate.run("pytest", [sys.executable, "-m", "pytest", "-q"])
    gate.run("static_check", [sys.executable, "scripts/static_check.py"])
    gate.run("compileall", [sys.executable, "-m", "compileall", "-q", "app", "scripts"])
    gate.run("alembic_current", [sys.executable, "-m", "alembic", "heads"])
    if args.staging_report:
        report_path = Path(args.staging_report)
        try:
            staging_payload = json.loads(report_path.read_text(encoding="utf-8"))
            artifact_summary = staging_payload.get("artifact_qa") or staging_payload.get("summary") or {}
            if not artifact_summary:
                for step in staging_payload.get("steps", []):
                    if step.get("name") == "operational_guidance_99x99_qa":
                        try:
                            artifact_summary = json.loads(step.get("stdout") or "{}")
                        except json.JSONDecodeError:
                            artifact_summary = {"raw_stdout": step.get("stdout", "")[-2000:]}
                        break
            gate.checks.append(
                {
                    "name": "staging_artifact_qa",
                    "ok": staging_payload.get("status") == "PASS",
                    "source_report": str(report_path),
                    "artifact_summary": artifact_summary,
                }
            )
        except Exception as exc:
            gate.checks.append(
                {
                    "name": "staging_artifact_qa",
                    "ok": False,
                    "source_report": str(report_path),
                    "stderr": str(exc),
                }
            )
    else:
        gate.run(
            "staging_artifact_qa",
            [sys.executable, "scripts/staging_gate.py", "--output", "runtime/staging-gate-v0.8.1"],
            timeout=900,
        )

    if args.env_file:
        preflight = [sys.executable, "scripts/production_preflight.py", "--env-file", args.env_file]
        if args.online:
            preflight += ["--online", "--require-directus-catalog"]
        gate.run("production_preflight", preflight, timeout=300)
        if args.online:
            if not args.base_url:
                gate.checks.append({"name": "production_canary", "ok": False, "stderr": "--base-url is required with --online"})
            else:
                gate.run(
                    "production_canary",
                    [
                        sys.executable,
                        "scripts/production_canary.py",
                        "--env-file",
                        args.env_file,
                        "--base-url",
                        args.base_url,
                    ],
                    timeout=600,
                )

    payload = json.dumps(gate.payload(), ensure_ascii=False, indent=2)
    print(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    return 0 if gate.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
