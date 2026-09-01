#!/usr/bin/env python3
"""Compose-secret CI-provisioning reconciliation (automatikus drift-blokkoló).

A gyökér ``docker-compose.yml`` ``secrets:`` deklarációi és a CI-provisioning
(``scripts/ci-provision-secrets.sh`` CANONICAL_SECRET_NAMES blokkja) közötti
eltérést determinisztikusan, fail-closed módon blokkolja:

- minden Compose secret, amelynek lokális default bind-source fájlja a
  ``./secrets/`` könyvtárban van, szerepelnie kell a provisioning-listában
  (hiányzó fájl nem fordulhat elő a runneren — Task64 RemoteCI hiba);
- a provisioning-lista minden bejegyzésének pontosan
  ``./secrets/<név>.txt`` Compose-deklarációra kell mutatnia (árva
  provisioning szintén FAIL);
- a repóban commitolt bind-source-ok (build_ca → ``./docker/no-extra-ca.pem``)
  a provisioning-listában tilosak (a commitolt placeholdert nem írja felül
  futásidejű érték);
- mindkét Compose CI workflow (``ci.yml``, ``platform-ci.yml``) meghívja a
  provisioning-szkriptet ÉS ezt az ellenőrzést, méghozzá az első
  ``docker compose`` lépés előtt;
- a provisioning-szkript kizárólag ``openssl rand`` értékeket generál:
  committed literal secret/credential nem lehet benne.

A diagnosztika csak neveket, útvonalakat és darabszámokat közöl; secret-érték
soha nem kerül a kimenetbe. A kimenet determinisztikus (rendezett listák).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
PROVISION_SCRIPT = REPO_ROOT / "scripts" / "ci-provision-secrets.sh"
CI_WORKFLOWS = (
    REPO_ROOT / ".github" / "workflows" / "ci.yml",
    REPO_ROOT / ".github" / "workflows" / "platform-ci.yml",
)

_SECRET_DIR_PREFIX = "./secrets/"
_DEFAULT_RE = re.compile(r"\$\{[A-Za-z0-9_]+:-([^}]*)\}")
_NO_DEFAULT_RE = re.compile(r"\$\{[A-Za-z0-9_]+(?::[^}-][^}]*)?\}")
_NAME_BEGIN = "# CANONICAL_SECRET_NAMES_BEGIN"
_NAME_END = "# CANONICAL_SECRET_NAMES_END"


def _parse_compose_secrets(text: str) -> dict[str, str]:
    """A gyökér docker-compose.yml top-level ``secrets:`` blokkja név → default
    bind-source mapként. Csak a 0-os behúzású blokk számít (a service-szintű
    ``secrets:`` listák nem); ismeretlen alakú sor fail-closed."""
    secrets: dict[str, str] = {}
    in_block = False
    current: str | None = None
    for line_number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not in_block:
            if line == "secrets:":
                in_block = True
            continue
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        if line.startswith("  ") and not line.startswith("    "):
            match = re.fullmatch(r"  ([A-Za-z0-9_]+):", line)
            if not match:
                raise ValueError(
                    f"compose secrets block: unexpected entry at line {line_number}"
                )
            current = match.group(1)
            if current in secrets:
                raise ValueError(f"compose secrets block: duplicate secret {current}")
            secrets[current] = ""
            continue
        if line.startswith("    file:"):
            source = line[len("    file:") :].strip()
            if current is None:
                raise ValueError(f"compose secrets block: file source without name (line {line_number})")
            default = _expand_default(source)
            secrets[current] = default
            continue
        raise ValueError(f"compose secrets block: unexpected line {line_number}")
    if not secrets:
        raise ValueError("compose secrets block: no declarations found")
    return secrets


def _expand_default(source: str) -> str:
    """A ``${VAR:-default}`` formátum defaultját adja vissza; default nélküli
    vagy egyéb formájú interpoláció fail-closed (a CI nem tudná
    determinisztikusan provisionálni)."""
    match = _DEFAULT_RE.fullmatch(source)
    if match:
        return match.group(1)
    if _NO_DEFAULT_RE.search(source):
        raise ValueError(
            "compose secrets block: bind source has no local default "
            f"({source!r}); CI provisioning cannot be deterministic"
        )
    return source


def _parse_provisioning_list(text: str) -> list[str]:
    """A provisioning-szkript CANONICAL_SECRET_NAMES blokkjának névlistája."""
    begin = text.find(_NAME_BEGIN)
    end = text.find(_NAME_END)
    if begin == -1 or end == -1 or end <= begin:
        raise ValueError("provisioning script: canonical names block markers missing")
    block = text[begin + len(_NAME_BEGIN) : end]
    names: list[str] = []
    for raw in block.splitlines():
        name = raw.strip()
        if not name or name.startswith("#"):
            continue
        if "=" in name or name == '"':
            # A változó-hozzárendelés fejlécsora (CANONICAL_SECRET_NAMES=")
            # és a blokk záró idézőjele része a blokknak, de nem névbejegyzés.
            continue
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise ValueError(f"provisioning script: unexpected name entry {name!r}")
        if name in names:
            raise ValueError(f"provisioning script: duplicate name entry {name}")
        names.append(name)
    if not names:
        raise ValueError("provisioning script: canonical names block is empty")
    return names


def _provisioning_forbids_literal_secrets(text: str) -> None:
    """A szkript kizárólag ``openssl rand`` generált értékeket hozhat létre.

    Pontos szabályok, érték-material nélkül: minden secret-fájlba író sor
    csak az ``openssl rand -hex 32`` generálás lehet; ``export`` tilos; a
    szkript nem olvas secret-értéket a környezetből (a ``CI_SECRET_DIR``
    kivételével, ami útvonal, nem érték).
    """
    if "openssl rand -hex 32" not in text:
        raise ValueError("provisioning script: openssl rand generation missing")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if (
            "> \"$SECRET_DIR" in line or "> \"${SECRET_DIR" in line
        ) and "openssl rand -hex 32" not in line:
            raise ValueError(
                "provisioning script: a secret file write is not generated by "
                "openssl rand"
            )
        if re.match(r"^\s*export\s", line):
            raise ValueError("provisioning script: export of values is forbidden")
        if re.match(r"^\s*[A-Za-z_][A-Za-z0-9_]*=", line):
            assignment = line.split("=", 1)[1].strip()
            # Literál-token hozzárendelés tilos: a szkriptben csak az
            # útvonal-változó (${CI_SECRET_DIR:-...}), a névlista-blokk és
            # a darabszám-számítás szerepelhet; egy hosszú, idézőjel/
            # változó nélküli literal secret-érték alakú token FAIL.
            if re.fullmatch(r"[A-Za-z0-9+/=_-]{8,}", assignment):
                raise ValueError(
                    "provisioning script: literal secret assignment found "
                    "(only the secret-directory path variable is allowed)"
                )


def reconcile(
    compose_text: str,
    provisioning_text: str,
    workflows: tuple[tuple[str, str], ...],
) -> tuple[int, str]:
    """A teljes reconciliation; ``(status, message)``, a message secretmentes."""
    failures: list[str] = []
    try:
        compose = _parse_compose_secrets(compose_text)
    except ValueError as exc:
        return 1, f"FAIL - {exc}"
    try:
        provisioned = _parse_provisioning_list(provisioning_text)
    except ValueError as exc:
        return 1, f"FAIL - {exc}"
    try:
        _provisioning_forbids_literal_secrets(provisioning_text)
    except ValueError as exc:
        return 1, f"FAIL - {exc}"

    provisioned_set = set(provisioned)
    for name, default in sorted(compose.items()):
        if default.startswith(_SECRET_DIR_PREFIX):
            expected = f"./secrets/{name}.txt"
            if default != expected:
                failures.append(
                    f"compose secret {name} default path {default!r} "
                    f"does not match its name ({expected!r})"
                )
            if name not in provisioned_set:
                failures.append(
                    f"compose secret {name} ({default}) is not provisioned by the CI script"
                )
        elif name in provisioned_set:
            failures.append(
                f"provisioning entry {name} is not a ./secrets/ compose declaration "
                f"(compose default: {default!r})"
            )
    for name in sorted(provisioned_set - set(compose)):
        failures.append(f"provisioning entry {name} has no compose secret declaration")
    if not (REPO_ROOT / "docker" / "no-extra-ca.pem").is_file():
        failures.append("committed build_ca placeholder docker/no-extra-ca.pem is missing")

    for workflow_name, text in workflows:
        if "sh scripts/ci-provision-secrets.sh" not in text:
            failures.append(f"{workflow_name} does not invoke the provisioning script")
            continue
        if "python scripts/check_ci_secret_provisioning.py" not in text:
            failures.append(f"{workflow_name} does not invoke the provisioning reconciliation")
        lines = text.splitlines()
        provision_at = next(
            (i for i, line in enumerate(lines) if "sh scripts/ci-provision-secrets.sh" in line),
            None,
        )
        check_at = next(
            (
                i
                for i, line in enumerate(lines)
                if "python scripts/check_ci_secret_provisioning.py" in line
            ),
            None,
        )
        first_compose = next(
            (i for i, line in enumerate(lines) if "docker compose" in line), None
        )
        if provision_at is None or check_at is None:
            continue
        if first_compose is not None:
            if provision_at >= first_compose:
                failures.append(
                    f"{workflow_name}: provisioning step must run before any docker compose step"
                )
            if check_at >= first_compose:
                failures.append(
                    f"{workflow_name}: reconciliation step must run before any docker compose step"
                )

    if failures:
        for line in failures:
            print(f"check_ci_secret_provisioning: FAIL - {line}", file=sys.stderr)
        return 1, "FAIL - Compose secret provisioning reconciliation failed"
    message = (
        f"PASS - {len(compose)} compose secret declaration(s) reconciled with "
        f"{len(provisioned)} CI provisioning entry/entries; "
        f"{len(workflows)} workflow(s) wired."
    )
    print(f"check_ci_secret_provisioning: {message}")
    return 0, message


def main() -> int:
    try:
        compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
        provisioning_text = PROVISION_SCRIPT.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"check_ci_secret_provisioning: FAIL - {exc}", file=sys.stderr)
        return 1
    workflows = tuple(
        (path.name, path.read_text(encoding="utf-8"))
        for path in CI_WORKFLOWS
    )
    status, _ = reconcile(compose_text, provisioning_text, workflows)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
