"""Task61/Task65 regresszió a path-szűk Semgrep sharding- és rule-kivétel
invariánsaira.

A ``.github/workflows/imperial-adas-semgrep.yml`` NÉGY, egymást kizáró
útvonalszeletet vizsgál (Task65 sharding):

1. platform-core kód (a Jinja-sablonok path-kizárásával, korlátos
   ``--timeout 30`` értékkel);
2. platform-core Jinja-sablonok (parser-kompatibilis shard);
3. a két npm projekt;
4. minden más path.

A rule-kivételek NEM globálisak, hanem exact path-ra szűkítettek, és
mindegyik mögött bizonyított, futó egyenértékű védelem áll:

- ``django-no-csrf-token``: csak a platform-core FastAPI/Jinja2 alkalmazás
  (nincs Django) — a CSRF endpoint/control mátrix
  (``tests/test_csrf_control_matrix.py``) + threat model bizonyítja a
  védelmet; minden más path (pl. Django template) a rule nélkül NEM fut,
  hanem a teljes szabályhalmazzal.
- ``npm-missing-minimum-release-age``: csak a két npm projekt
  (imperial-sales-crm, itep-core), mindkettőben futó, tesztelt 7 napos
  package-age kapu (``scripts/check-package-age.mjs``, Quality CI).
- ``missing-integrity``/``plaintext-http-link`` (html): csak a
  platform-core sablonkönyvtár, mert a semgrep html-parsere a Jinja-
  szintaxist nem tudja teljesen parse-olni; a kompenzáló ellenőrzés a
  ``scripts/check_scan_exception_compensations.py`` (determinisztikus
  tulajdonság-ellenőrzés ugyanazon a path-körön), és minden más HTML path
  a rest scanben a teljes szabályhalmazzal fut.

Ez a teszt a kivételek hangosság-feltételeit zárolja:

- a scan megtartja az ``--config auto`` + ``--error`` fail-closed kaput;
- a kivételhalmaz PONTOSAN a dokumentált négy rule, és mindegyik kizárólag
  a saját, path-szűk scan-invokációjában szerepel;
- a repo útvonalai pontosan partícionáltak: a fennmaradó scan a három
  kivételezett útvonalat ``--exclude``-olja, minden más path a teljes
  szabályhalmazzal fut;
- a platform-core kód-scan korlátos, dokumentált ``--timeout 30``
  per-rule-per-file értéket használ (a pinelt 1.172.0 alapértéke 5 s; a
  main.py/models.py taint-szabály timeoutjait ez szünteti meg, egy 30 s-t
  is túllépő szabály továbbra is fail-closed Timeout hibát ad);
- nincs globális exclude (.semgrepignore), severity- vagy küszöbcsökkentés;
- a template-ekben nincs inline ``nosemgrep`` CSRF-megjegyzés;
- mindkét npm projekt package-age kapuja létezik és CI-be van kötve
  (CI-default ``includeDev=true``: a dev/devOptional függőségek is vizsgáltak);
- a workflow-kben minden ``uses:`` ref 40-hexes commit SHA-ra pinelt;
- a bizonyíték-egyesítő lépés létezik, determinisztikusan fut és mind a
  négy részt egyesíti;
- a kompenzáló ellenőrzés lépése létezik és fail-closed;
- minden részscan, az egyesítő, a kompenzáló ellenőrzés és az összesített
  enforcement kapu ``if: always()`` mellett fut, miközben a lépések a scan
  saját exit kódját őrzik meg (``<rész>.exit``, ``exit "$status"``) — nincs
  continue-on-error, a job-összegzés nem zöldül;
- az összesített enforcement kapu hiányos/hibás bizonyíték, nem nulla scan
  exit vagy CRITICAL/HIGH/ERROR találat esetén fail-closed;
- az összesített enforcement kapu bármely részscan — a templates shardot is
  beleértve — hiányzó, nem lista típusú vagy nem üres ``errors`` mezője
  esetén fail-closed (a belső Semgrep hibákat az exit 0 sem zöldítheti).

Ha bármely feltétel megszűnik, a kivételt vissza kell vonni.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SEMGREP_WORKFLOW = REPO / ".github" / "workflows" / "imperial-adas-semgrep.yml"
TEMPLATES_DIR = REPO / "services" / "platform-core" / "app" / "templates"

CSRF_RULE_ID = "python.django.security.django-no-csrf-token.django-no-csrf-token"
NPM_RULE_ID = "package_managers.npm.npm-missing-minimum-release-age.npm-missing-minimum-release-age"
HTML_INTEGRITY_RULE_ID = "html.security.audit.missing-integrity.missing-integrity"
HTML_PLAINTEXT_HTTP_RULE_ID = "html.security.plaintext-http-link.plaintext-http-link"

DOCUMENTED_EXCLUDE_RULES = {
    CSRF_RULE_ID,
    NPM_RULE_ID,
    HTML_INTEGRITY_RULE_ID,
    HTML_PLAINTEXT_HTTP_RULE_ID,
}
NARROW_TARGETS = {
    "services/platform-core",
    "services/imperial-sales-crm",
    "services/itep-core",
}
PLATFORM_CORE_TEMPLATES_TARGET = "services/platform-core/app/templates"
SCAN_PARTS = (
    "semgrep-platform-core.json",
    "semgrep-platform-core-templates.json",
    "semgrep-npm.json",
    "semgrep-rest.json",
)


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
    assert len(_scan_blocks(source)) == 4


def test_csrf_exclusion_is_scoped_to_platform_core_shards_only() -> None:
    # A CSRF-kivétel kizárólag a platform-core útvonalú shardokban állhat
    # (kód-scan + templates-scan), más path-scanben nem.
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    csrf_blocks = [block for block in blocks if CSRF_RULE_ID in block]
    assert len(csrf_blocks) == 2, (
        "a CSRF rule-kivételnek pontosan a két platform-core shardban kell állnia"
    )
    for block in csrf_blocks:
        lines = _command_lines(block)
        assert "services/platform-core" in " ".join(lines), (
            "a CSRF-kivétel csak platform-core célpontú shardban állhat"
        )
        assert NPM_RULE_ID not in block, (
            "az npm-kivétel nem állhat a CSRF-kivétellel közös shardban"
        )
    # A többi path-scan (npm, rest) nem tartalmazhatja a CSRF-kivételt.
    other_blocks = [block for block in blocks if block not in csrf_blocks]
    assert all(CSRF_RULE_ID not in block for block in other_blocks)


def test_platform_core_code_shard_uses_bounded_timeout_and_excludes_only_templates() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    code_blocks = [block for block in blocks if "semgrep-platform-core.json" in block]
    assert len(code_blocks) == 1
    block = code_blocks[0]
    assert "--timeout 30" in block, "a kód-scan korlátos, dokumentált timeoutja hiányzik"
    lines = _command_lines(block)
    excludes = [line for line in lines if line.startswith("--exclude ")]
    # A Dockerfile a scanben MARAD (a dockerfile-szabályok lefedik); csak a
    # Jinja-sablonkönyvtár kerül a saját parser-kompatibilis shardjába.
    assert excludes == [f"--exclude {PLATFORM_CORE_TEMPLATES_TARGET}"], (
        f"nem várt path-kizárás a platform-core kód-scanben: {excludes}"
    )
    assert "--output semgrep-platform-core.json" in block


def test_html_exclusions_are_scoped_to_the_templates_shard_only() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    html_blocks = [
        block
        for block in blocks
        if HTML_INTEGRITY_RULE_ID in block or HTML_PLAINTEXT_HTTP_RULE_ID in block
    ]
    assert len(html_blocks) == 1, (
        "a html-rule kivételeknek pontosan egy shardban kell állniuk"
    )
    block = html_blocks[0]
    lines = _command_lines(block)
    assert any(HTML_INTEGRITY_RULE_ID in line for line in lines)
    assert any(HTML_PLAINTEXT_HTTP_RULE_ID in line for line in lines)
    assert any(PLATFORM_CORE_TEMPLATES_TARGET in line for line in lines), (
        "a html-kivétel csak a sablonkönyvtárra szűkíthető"
    )
    assert "--output semgrep-platform-core-templates.json" in block
    # A shard nem zár ki path-t: csak a két html-rule kivétel + a CSRF-kivétel.
    assert not any(line.startswith("--exclude ") for line in lines)
    # A sablon-shard a platform-core része, így a CSRF-kivétel itt is érvényes.
    assert any(CSRF_RULE_ID in line for line in lines)


def test_templates_shard_targets_exactly_the_templates_directory() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    block = _block_for(source, "Run targeted SAST (platform-core Jinja templates")
    lines = _command_lines(block)
    targets = [
        line for line in lines if line.startswith("services/platform-core")
    ]
    assert targets == [PLATFORM_CORE_TEMPLATES_TARGET], (
        f"a sablon-shard célpontja pontosan a sablonkönyvtár lehet: {targets}"
    )


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
    assert HTML_INTEGRITY_RULE_ID not in block
    assert not any(line.startswith("--exclude ") for line in lines)


def test_remaining_scan_runs_the_full_rule_set_on_everything_else() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    blocks = _scan_blocks(source)
    rest_blocks = [
        block
        for block in blocks
        if CSRF_RULE_ID not in block
        and NPM_RULE_ID not in block
        and HTML_INTEGRITY_RULE_ID not in block
        and HTML_PLAINTEXT_HTTP_RULE_ID not in block
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
    assert "--exclude-rule" in source  # a négy dokumentált, path-szűk kivétel
    excluded = set(re.findall(r"--exclude-rule\s+([^\s]+)", source))
    assert excluded == DOCUMENTED_EXCLUDE_RULES, f"eltérő kivételhalmaz: {excluded}"


def test_semgrep_evidence_merge_step_and_script_exist() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/merge_semgrep_evidence.py" in source
    merge_script = REPO / "scripts" / "merge_semgrep_evidence.py"
    assert merge_script.is_file()
    merge_source = merge_script.read_text(encoding="utf-8")
    for part in SCAN_PARTS:
        assert f'"{part}"' in merge_source, f"{part} hiányzik a merge-szkriptből"
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

    parts = {
        "semgrep-platform-core.json": {
            "version": "1.172.0",
            "results": [{"rule": "a"}],
            "errors": [],
        },
        "semgrep-platform-core-templates.json": {
            "version": "1.172.0",
            "results": [{"rule": "tpl"}],
            "errors": [],
        },
        "semgrep-npm.json": {"version": "1.172.0", "results": [], "errors": [{"code": 2}]},
        "semgrep-rest.json": {"version": "1.172.0", "results": [{"rule": "b"}], "errors": []},
    }
    for name, payload in parts.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert merge_module.main() == 0
    merged = json.loads((tmp_path / "semgrep.json").read_text(encoding="utf-8"))
    assert [item["rule"] for item in merged["results"]] == ["a", "tpl", "b"]
    assert [item["code"] for item in merged["errors"]] == [2]
    # A részek közül bármelyik hiánya fail-closed.
    (tmp_path / "semgrep-platform-core-templates.json").unlink()
    assert merge_module.main() == 1


def test_compensation_check_step_and_script_exist() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    block = _block_for(source, "Verify rule-exception compensating checks")
    assert "python scripts/check_scan_exception_compensations.py" in block
    assert "if: always()" in _command_lines(block)
    checker = REPO / "scripts" / "check_scan_exception_compensations.py"
    assert checker.is_file()
    checker_source = checker.read_text(encoding="utf-8")
    assert "missing-integrity" in checker_source
    assert "plaintext-http-link" in checker_source


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
    "Run targeted SAST (platform-core code, CSRF",
    "Run targeted SAST (platform-core Jinja templates",
    "Run targeted SAST (npm projects",
    "Run targeted SAST (all remaining paths",
)


def test_every_scan_merge_and_enforcement_step_runs_with_if_always() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    for step_name in SCAN_STEP_NAMES + (
        "Verify rule-exception compensating checks",
        "Merge Semgrep evidence",
        "Enforce Semgrep verdict",
    ):
        block = _block_for(source, step_name)
        assert "if: always()" in _command_lines(block), f"{step_name}: hiányzó if: always()"


def test_scans_preserve_exit_codes_and_artifacts_without_greening() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in source
    for part in SCAN_PARTS:
        exit_name = part.replace(".json", ".exit")
        assert exit_name in source
    assert source.count('exit "$status"') == 4
    upload = _block_for(source, "Upload Semgrep evidence")
    for part in SCAN_PARTS:
        assert part in upload
        assert part.replace(".json", ".exit") in upload


def test_enforcement_step_and_script_exist() -> None:
    source = SEMGREP_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/enforce_semgrep_verdict.py" in source
    enforce_script = REPO / "scripts" / "enforce_semgrep_verdict.py"
    assert enforce_script.is_file()
    enforce_source = enforce_script.read_text(encoding="utf-8")
    for part in SCAN_PARTS:
        assert f'"{part}"' in enforce_source, f"{part} hiányzik az enforce-szkriptből"
        assert f'"{part.replace(".json", ".exit")}"' in enforce_source


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


def _write_scan_part(
    tmp_path,
    part: str,
    results: list[dict],
    exit_code: str = "0",
    errors: Any | None = None,
    include_errors: bool = True,
) -> None:
    payload: dict[str, Any] = {"version": "1.172.0", "results": results}
    if include_errors:
        payload["errors"] = [] if errors is None else errors
    (tmp_path / part).write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / part.replace(".json", ".exit")).write_text(exit_code, encoding="utf-8")


def _write_all_clean_parts(
    tmp_path,
    override_part: str | None = None,
    override_results: list[dict] | None = None,
    exit_code: str = "0",
    errors: Any | None = None,
    include_errors: bool = True,
) -> None:
    """Mind a négy részscan bizonyítékát megírja; az override_part kapja a
    megadott speciális tartalmat."""
    for part in SCAN_PARTS:
        if part == override_part:
            _write_scan_part(
                tmp_path,
                part,
                override_results if override_results is not None else [],
                exit_code=exit_code,
                errors=errors,
                include_errors=include_errors,
            )
        else:
            _write_scan_part(tmp_path, part, [])


def test_enforcement_passes_on_complete_clean_scans(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path,
        override_part="semgrep-rest.json",
        override_results=[{"check_id": "warn.rule", "extra": {"severity": "WARNING"}}],
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 0


def test_enforcement_fails_on_blocking_finding(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path,
        override_part="semgrep-platform-core.json",
        override_results=[{"check_id": "block.rule", "extra": {"severity": "ERROR"}}],
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_on_missing_scan_evidence(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(tmp_path)
    (tmp_path / "semgrep-platform-core-templates.json").unlink()
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_on_early_scan_nonzero_exit(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path, override_part="semgrep-platform-core.json", exit_code="1"
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_when_merge_did_not_produce_evidence(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_fails_on_unparsable_scan_evidence(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(tmp_path)
    (tmp_path / "semgrep-platform-core.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "semgrep-platform-core.exit").write_text("0", encoding="utf-8")
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1


def test_enforcement_passes_on_empty_errors_field(tmp_path, monkeypatch) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(tmp_path, errors=[])
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 0


def test_enforcement_fails_on_nonempty_errors_with_exit_zero(
    tmp_path, monkeypatch, capsys
) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path,
        override_part="semgrep-platform-core.json",
        errors=[{"code": 3, "type": "UnknownLanguageError", "message": "n/a"}],
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1
    stderr = capsys.readouterr().err
    assert "semgrep-platform-core.json" in stderr
    assert "internal errors" in stderr
    assert "UnknownLanguageError" not in stderr  # secretmentes diagnosztika


def test_enforcement_fails_on_nonempty_errors_in_templates_part(
    tmp_path, monkeypatch, capsys
) -> None:
    # Task65 error-free evidence szerződés: a templates-shard belső hibái
    # ugyanúgy fail-closed — az exit 0 nem zöldítheti a részscant.
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path,
        override_part="semgrep-platform-core-templates.json",
        errors=[{"code": 2, "type": "PartialParsing", "message": "n/a"}],
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1
    stderr = capsys.readouterr().err
    assert "semgrep-platform-core-templates.json" in stderr
    assert "internal errors" in stderr
    assert "PartialParsing" not in stderr  # secretmentes diagnosztika


def test_enforcement_fails_on_missing_errors_field(tmp_path, monkeypatch, capsys) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path,
        override_part="semgrep-platform-core.json",
        include_errors=False,
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1
    stderr = capsys.readouterr().err
    assert "semgrep-platform-core.json" in stderr
    assert "missing errors list" in stderr


def test_enforcement_fails_on_non_list_errors_field(tmp_path, monkeypatch, capsys) -> None:
    module = _enforcement_module()
    _write_all_clean_parts(
        tmp_path,
        override_part="semgrep-platform-core.json",
        errors="boom",
    )
    (tmp_path / "semgrep.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert module.main() == 1
    stderr = capsys.readouterr().err
    assert "semgrep-platform-core.json" in stderr
    assert "errors is not a list" in stderr
