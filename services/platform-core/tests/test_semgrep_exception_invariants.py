"""Task61 regresszió a path-szűk Semgrep rule-kivételek invariánsaira.

A ``.github/workflows/imperial-adas-semgrep.yml`` három, egymást kizáró
útvonalszeletet vizsgál. A két rule-kivétel NEM globális, hanem exact
path-ra szűkített, és mindegyik mögött bizonyított, futó egyenértékű
védelem áll:

- ``django-no-csrf-token``: csak a platform-core FastAPI/Jinja2 alkalmazás
  (nincs Django) — a CSRF endpoint/control mátrix
  (``tests/test_csrf_control_matrix.py``) + threat model bizonyítja a
  védelmet; minden más path (pl. Django template) a rule nélkül NEM fut,
  hanem a teljes szabályhalmazzal.
- ``npm-missing-minimum-release-age``: csak a két npm projekt
  (imperial-sales-crm, itep-core), mindkettőben futó, tesztelt 7 napos
  package-age kapu (``scripts/check-package-age.mjs``, Quality CI).

Ez a teszt a kivételek hangosság-feltételeit zárolja:

- a scan megtartja az ``--config auto`` + ``--error`` fail-closed kaput;
- a kivételhalmaz PONTOSAN a dokumentált két rule, és mindegyik kizárólag
  a saját, path-szűk scan-invokációjában szerepel;
- a repo útvonalai pontosan partícionáltak: a fennmaradó scan a két
  kivételezett path-t ``--exclude``-olja, minden más path a teljes
  szabályhalmazzal fut;
- nincs globális exclude (.semgrepignore), severity- vagy küszöbcsökkentés;
- a template-ekben nincs inline ``nosemgrep`` CSRF-megjegyzés;
- mindkét npm projekt package-age kapuja létezik és CI-be van kötve
  (CI-default ``includeDev=true``: a dev/devOptional függőségek is vizsgáltak);
- a workflow-kben minden ``uses:`` ref 40-hexes commit SHA-ra pinelt;
- a bizonyíték-egyesítő lépés létezik és determinisztikusan fut;
- minden részscan, az egyesítő és az összesített enforcement kapu
  ``if: always()`` mellett fut, miközben a lépések a scan saját exit kódját
  őrzik meg (``<rész>.exit``, ``exit "$status"``) — nincs continue-on-error,
  a job-összegzés nem zöldül;
- az összesített enforcement kapu hiányos/hibás bizonyíték, nem nulla scan
  exit vagy CRITICAL/HIGH/ERROR találat esetén fail-closed.

Ha bármely feltétel megszűnik, a kivételt vissza kell vonni.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SEMGREP_WORKFLOW = REPO / ".github" / "workflows" / "imperial-adas-semgrep.yml"
TEMPLATES_DIR = REPO / "services" / "platform-core" / "app" / "templates"

CSRF_RULE_ID = "python.django.security.django-no-csrf-token.django-no-csrf-token"
NPM_RULE_ID = "package_managers.npm.npm-missing-minimum-release-age.npm-missing-minimum-release-age"

DOCUMENTED_EXCLUDE_RULES = {CSRF_RULE_ID, NPM_RULE_ID}
NARROW_TARGETS = {
    "services/platform-core",
    "services/imperial-sales-crm",
    "services/itep-core",
}


def _command_lines(workflow_source: str) -> list[str]:
    """A workflow összes, megjegyzés nélküli sora."""
    return [
        line.strip()
        for line in workflow_source.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _scan_blocks(workflow_source: str) -> list[str]:
    """A `- name:`/`- uses:` lépéshatárok közötti szövegblokkok."""
    blocks = re.split(r"(?m)^\s*- (?:name|uses):", workflow_source)
    return [block for block in blocks if "semgrep scan" in block]


def _step_blocks(workflow_source: str) -> list[str]:
    """A lépések szövegblokkjai a `- name:`/`- uses:` fejlécekkel együtt."""
    return re.split(r"(?m)(?=^\s*- (?:name|uses):)", workflow_source)


def _block_for(workflow_source: str, step_name: str) -> str:
    """A megadott nevű lépés blokkja (a headerrel együtt)."""
    for block in _step_blocks(workflow_source):
        lines = block.splitlines()
        if lines and step_name in lines[0]:
            return block
    raise AssertionError(f"missing workflow step: {step_name}")


def test_semgrep_scan_keeps_auto_config_and_error_gate() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "--config auto" in source
    assert "--error" in source
    assert "--no-rewrite-rule-ids" in source
    assert "semgrep==1.172.0" in source
    assert len(_scan_blocks(source)) == 3


def test_csrf_exclusion_is_scoped_to_the_platform_core_scan_only() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    csrf_blocks = [block for block in blocks if CSRF_RULE_ID in block]
    assert len(csrf_blocks) == 1, "a CSRF rule-kivételnek pontosan egy scan-blokkban kell állnia"
    block = csrf_blocks[0]
    lines = _command_lines(block)
    assert "services/platform-core" in lines, "a CSRF-kivétel csak a platform-core scan célpontja lehet"
    assert "--output semgrep-platform-core.json" in block
    assert NPM_RULE_ID not in block
    # A CSRF-kivétel scanje nem zár ki más path-t: minden más szabály fut rajta.
    assert not any(line.startswith("--exclude ") for line in lines)


def test_npm_exclusion_is_scoped_to_the_two_gated_npm_projects_only() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    npm_blocks = [block for block in blocks if NPM_RULE_ID in block]
    assert len(npm_blocks) == 1, "az npm rule-kivételnek pontosan egy scan-blokkban kell állnia"
    block = npm_blocks[0]
    lines = _command_lines(block)
    assert any("services/imperial-sales-crm" in line for line in lines)
    assert any("services/itep-core" in line for line in lines)
    assert "--output semgrep-npm.json" in block
    assert CSRF_RULE_ID not in block
    assert not any(line.startswith("--exclude ") for line in lines)


def test_remaining_scan_runs_the_full_rule_set_on_everything_else() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    rest_blocks = [
        block
        for block in blocks
        if CSRF_RULE_ID not in block and NPM_RULE_ID not in block
    ]
    assert len(rest_blocks) == 1
    block = rest_blocks[0]
    lines = _command_lines(block)
    assert not any("--exclude-rule" in line for line in lines)
    assert "--output semgrep-rest.json" in block
    for target in sorted(NARROW_TARGETS):
        assert f"--exclude {target}" in lines, f"{target} hiányzik a fennmaradó scan kizárásából"
    assert "." in lines


def test_no_global_exclusion_or_severity_threshold_change() -> None:
    assert not (REPO / ".semgrepignore").exists()
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "--severity" not in source
    assert "--exclude-rule" in source  # a két dokumentált, path-szűk kivétel
    excluded = set(re.findall(r"--exclude-rule\s+([^\s]+)", source))
    assert excluded == DOCUMENTED_EXCLUDE_RULES, f"eltérő kivételhalmaz: {excluded}"


def test_semgrep_evidence_merge_step_and_script_exist() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/merge_semgrep_evidence.py" in source
    merge_script = REPO / "scripts" / "merge_semgrep_evidence.py"
    assert merge_script.is_file()
    assert "actions/upload-artifact" in source


def test_merge_script_deterministically_merges_scan_parts(tmp_path, monkeypatch) -> None:
    import importlib.util
    import sys

    merge_path = REPO / "scripts" / "merge_semgrep_evidence.py"
    spec = importlib.util.spec_from_file_location("merge_semgrep_evidence", merge_path)
    merge_module = importlib.util.module_from_spec(spec)
    sys.modules["merge_semgrep_evidence"] = merge_module
    assert spec.loader is not None
    spec.loader.exec_module(merge_module)

    (tmp_path / "semgrep-platform-core.json").write_text(
        json.dumps({"version": "1.172.0", "results": [{"rule": "a"}], "errors": []}),
        encoding="utf-8",
    )
    (tmp_path / "semgrep-npm.json").write_text(
        json.dumps({"version": "1.172.0", "results": [], "errors": [{"code": 2}]}),
        encoding="utf-8",
    )
    (tmp_path / "semgrep-rest.json").write_text(
        json.dumps({"version": "1.172.0", "results": [{"rule": "b"}], "errors": []}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert merge_module.main() == 0
    merged = json.loads((tmp_path / "semgrep.json").read_text(encoding="utf-8"))
    assert [item["rule"] for item in merged["results"]] == ["a", "b"]
    assert [item["code"] for item in merged["errors"]] == [2]
    # A részek közül bármelyik hiánya fail-closed.
    (tmp_path / "semgrep-rest.json").unlink()
    assert merge_module.main() == 1


def test_no_inline_csrf_nosemgrep_comments_in_templates() -> None:
    for template_path in TEMPLATES_DIR.glob("*.html"):
        text = template_path.read_text(encoding="utf-8")
        assert "django-no-csrf-token" not in text, (
            f"{template_path.name}: inline CSRF nosemgrep megjegyzés tilos "
            "(path-szűk központi rule-kivétel van helyette)"
        )


def test_csrf_threat_model_document_exists() -> None:
    assert (REPO / "services" / "platform-core" / "docs" / "csrf-threat-model.md").is_file()


def test_both_npm_projects_have_a_running_tested_package_age_gate() -> None:
    for service in ("services/imperial-sales-crm", "services/itep-core"):
        check = REPO / service / "scripts" / "check-package-age.mjs"
        assert check.is_file(), f"{service}: package-age kapu hiányzik"
        test = REPO / service / "tests" / "package-age-check.test.mjs"
        assert test.is_file(), f"{service}: package-age teszt hiányzik"
    quality = (REPO / ".github" / "workflows" / "quality.yml").read_text(encoding="utf-8")
    assert quality.count("node scripts/check-package-age.mjs") == 2
    for service in ("services/imperial-sales-crm", "services/itep-core"):
        npmrc = REPO / service / ".npmrc"
        if npmrc.is_file():
            assert "minimum-release-age" not in npmrc.read_text(encoding="utf-8")


def test_no_mutable_action_refs_remain_in_branch_workflows() -> None:
    uses_re = re.compile(r"^\s*uses:\s*(\S+)")
    for workflow_path in sorted((REPO / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(
            workflow_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = uses_re.search(line)
            if not match or "@" not in match.group(1):
                continue
            _action, ref = match.group(1).rsplit("@", 1)
            assert re.fullmatch(r"[0-9a-f]{40}", ref), (
                f"{workflow_path.name}:{line_number} mutable action ref: {match.group(1)}"
            )


SCAN_STEP_NAMES = (
    "Run targeted SAST (platform-core",
    "Run targeted SAST (npm projects",
    "Run targeted SAST (all remaining paths",
)


def test_every_scan_merge_and_enforcement_step_runs_with_if_always() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    for step_name in SCAN_STEP_NAMES + ("Merge Semgrep evidence", "Enforce Semgrep verdict"):
        block = _block_for(source, step_name)
        assert "if: always()" in _command_lines(block), f"{step_name}: hiányzó if: always()"


def test_scans_preserve_exit_codes_and_artifacts_without_greening() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in source
    for part in ("semgrep-platform-core", "semgrep-npm", "semgrep-rest"):
        assert f"{part}.exit" in source
    assert source.count('exit "$status"') == 3
    upload = _block_for(source, "Upload Semgrep evidence")
    for part in ("semgrep-platform-core", "semgrep-npm", "semgrep-rest"):
        assert f"{part}.json" in upload
        assert f"{part}.exit" in upload


def test_enforcement_step_and_script_exist() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/enforce_semgrep_verdict.py" in source
    assert (REPO / "scripts" / "enforce_semgrep_verdict.py").is_file()


def _enforcement_module():
    import importlib.util
    import sys

    enforce_path = REPO / "scripts" / "enforce_semgrep_verdict.py"
    spec = importlib.util.spec_from_file_location("enforce_semgrep_verdict", enforce_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["enforce_semgrep_verdict"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_scan_part(tmp_path, part: str, results: list[dict], exit_code: str = "0") -> None:
    (tmp_path / part).write_text(
        json.dumps({"version": "1.172.0", "results": results, "errors": []}),
        encoding="utf-8",
    )
    (tmp_path / part.replace(".json", ".exit")).write_text(exit_code, encoding="utf-8")


def test_enforcement_passes_on_complete_clean_scans(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_scan_part(tmp_path, "semgrep-platform-core.json", [])
    _write_scan_part(tmp_path, "semgrep-npm.json", [])
    _write_scan_part(
        tmp_path,
        "semgrep-rest.json",
        [{"check_id": "warn.rule", "extra": {"severity": "WARNING"}}],
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 0


def test_enforcement_fails_on_blocking_finding(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_scan_part(
        tmp_path,
        "semgrep-platform-core.json",
        [{"check_id": "block.rule", "extra": {"severity": "ERROR"}}],
    )
    _write_scan_part(tmp_path, "semgrep-npm.json", [])
    _write_scan_part(tmp_path, "semgrep-rest.json", [])
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_on_missing_scan_evidence(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_scan_part(tmp_path, "semgrep-platform-core.json", [])
    _write_scan_part(tmp_path, "semgrep-npm.json", [])
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_on_early_scan_nonzero_exit(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_scan_part(tmp_path, "semgrep-platform-core.json", [], exit_code="1")
    _write_scan_part(tmp_path, "semgrep-npm.json", [])
    _write_scan_part(tmp_path, "semgrep-rest.json", [])
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_when_merge_did_not_produce_evidence(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_scan_part(tmp_path, "semgrep-platform-core.json", [])
    _write_scan_part(tmp_path, "semgrep-npm.json", [])
    _write_scan_part(tmp_path, "semgrep-rest.json", [])
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1
