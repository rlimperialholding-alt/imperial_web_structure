"""Fail closed unless the platform-core typecheck runtime is policy-compatible.

The configured static-quality gate is ``python -m mypy app --config-file
pyproject.toml``. That command is only as deterministic as the runtime behind
it: the mypyc-compiled mypy wheel ships one native extension module per mypy
module, and mypy 1.19+ additionally requires the binary-only ``librt``. A
Windows application-control policy can refuse to load those unsigned,
user-installed binaries (observed: ``ImportError: DLL load failed while
importing base64`` from ``mypy/build.py``), failing the gate without a single
source-level type error. The fix is a runtime the policy cannot object to,
not a weaker gate: the runtime contract is declared in this audited script
(``_PURE_MYPY_VERSION``, the last mypy release without a mandatory
binary-only dependency, installed from its pure-Python source distribution),
the installed distribution is fail-closed verified against it, and an exact
``mypy==`` pin in ``requirements-dev.txt`` must agree with the declaration --
an unlocked range stays acceptable only because this declaration, not the
range, is the audited contract. Nothing about mypy's checked scope,
configuration, strictness or exit-code semantics changes. Verification
proves: the installed version matches, ``mypy.build`` is genuinely loaded
(never vacuously), and every loaded ``mypy``/``mypyc``/``librt`` module is
backed by a ``.py`` source file. Messages never carry secrets.
"""

from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Mapping
from importlib import machinery, metadata
from pathlib import Path
from typing import Any

PLATFORM_CORE_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = PLATFORM_CORE_ROOT / "requirements-dev.txt"
_MYPY_DISTRIBUTION = "mypy"
# The audited runtime contract: the last mypy release without the mandatory,
# binary-only ``librt`` dependency. The installed distribution must match
# exactly, and an exact ``mypy==`` pin in requirements-dev.txt must agree.
_PURE_MYPY_VERSION = "1.18.2"
# The distributions that make up the typecheck runtime itself. ``librt`` is
# listed because mypy 1.19+ imports it from ``mypy.build``; it must never
# appear as a loaded native module under the pure-Python runtime.
_RUNTIME_PACKAGES = frozenset({"mypy", "mypyc", "librt"})
# The canary module: its native import was the one the application-control
# policy denied, so a runtime that never loaded it proves nothing.
_REQUIRED_RUNTIME_MODULE = "mypy.build"
# Platform-independent on purpose: the same check must hold on the Windows
# worker and on a POSIX runner, so both native suffix families are rejected
# regardless of the host that runs the verification.
_NATIVE_SUFFIXES = tuple(sorted({*machinery.EXTENSION_SUFFIXES, ".pyd", ".so", ".dll"}))
_EXACT_PIN_RE = re.compile(r"(?m)^\s*mypy==([0-9][0-9A-Za-z.*+!-]*)\s*$")


class TypecheckRuntimeError(Exception):
    """Fail-closed typecheck-runtime condition; carries no secret material."""


def declared_pure_mypy_version(requirements_text: str) -> str:
    """The declared pure-Python mypy version, with requirements consistency.
    """
    pins = _EXACT_PIN_RE.findall(requirements_text)
    if len(pins) > 1:
        raise TypecheckRuntimeError(
            "requirements-dev.txt must not pin mypy to several versions."
        )
    if pins and pins[0] != _PURE_MYPY_VERSION:
        raise TypecheckRuntimeError(
            f"requirements-dev.txt pins mypy to {pins[0]}, which disagrees with "
            f"the declared pure runtime {_PURE_MYPY_VERSION}."
        )
    return _PURE_MYPY_VERSION


def native_runtime_modules(modules: Mapping[str, Any]) -> list[str]:
    """Loaded typecheck-runtime modules backed by a native extension file.
    """
    flagged: list[str] = []
    for name, module in sorted(modules.items()):
        if name.partition(".")[0] not in _RUNTIME_PACKAGES:
            continue
        origin = getattr(module, "__file__", None)
        if origin is None:
            continue
        if str(origin).endswith(_NATIVE_SUFFIXES):
            flagged.append(name)
    return flagged


def verify_typecheck_runtime(
    requirements_text: str,
    modules: Mapping[str, Any],
    installed_version: str,
) -> str:
    """Verify the declared version, the installed version and the loaded runtime.
    """
    declared = declared_pure_mypy_version(requirements_text)
    if installed_version != declared:
        raise TypecheckRuntimeError(
            f"installed mypy {installed_version} is not the declared pure "
            f"runtime {declared}."
        )
    if _REQUIRED_RUNTIME_MODULE not in modules:
        raise TypecheckRuntimeError(
            f"typecheck runtime was not exercised: {_REQUIRED_RUNTIME_MODULE} is not loaded."
        )
    flagged = native_runtime_modules(modules)
    if flagged:
        raise TypecheckRuntimeError(
            "typecheck runtime loads native extension module(s): " + ", ".join(flagged) + "."
        )
    verified = sum(1 for name in modules if name.partition(".")[0] in _RUNTIME_PACKAGES)
    return f"pure-Python mypy {declared}; {verified} runtime module(s) verified as source-backed"


def main() -> int:
    try:
        importlib.import_module(_REQUIRED_RUNTIME_MODULE)
    except ImportError as exc:
        # A denied native import lands here. The reason is reported because an
        # operator needs it to tell an application-control denial apart from a
        # missing dependency; it contains no secret material.
        print(
            "Typecheck runtime FAIL: the typecheck runtime is not importable "
            f"({exc.__class__.__name__}: {exc})."
        )
        return 2
    try:
        installed = metadata.version(_MYPY_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        print(f"Typecheck runtime FAIL: the {_MYPY_DISTRIBUTION} distribution is not installed.")
        return 2
    try:
        summary = verify_typecheck_runtime(
            REQUIREMENTS_PATH.read_text(encoding="utf-8"), sys.modules, installed
        )
    except OSError:
        print("Typecheck runtime FAIL: requirements-dev.txt could not be read.")
        return 2
    except TypecheckRuntimeError as exc:
        print(f"Typecheck runtime FAIL: {exc}")
        return 1
    print(f"Typecheck runtime PASS: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
