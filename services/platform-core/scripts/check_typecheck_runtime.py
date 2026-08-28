"""Fail closed unless the platform-core typecheck runtime is policy-compatible.

The configured static-quality gate is ``python -m mypy app --config-file
pyproject.toml``. That command is only as deterministic as the runtime behind
it, and on Windows the runtime is exactly where it stopped being deterministic:
the mypyc-compiled mypy wheel ships one native extension module per mypy
module, and mypy 1.19+ additionally requires ``librt``, which is published as
binary wheels only. A Windows application-control policy can refuse to load any
of those unsigned, user-installed binaries -- the observed failure was
``ImportError: DLL load failed while importing base64`` raised from
``mypy/build.py`` -- and the gate then fails with exit code 1 without a single
source-level type error, on an input that type-checks cleanly elsewhere.

The fix is a runtime the policy cannot object to, not a weaker gate: mypy is
pinned to the last release without a mandatory binary-only dependency and
installed from its pure-Python source distribution (``--no-binary mypy`` in
``requirements-dev.txt``), so ``python -m mypy`` loads ``.py`` modules only.
Nothing about mypy's checked scope, configuration, strictness or exit-code
semantics changes.

This module makes that property provable rather than incidental. It verifies,
fail-closed:

* ``requirements-dev.txt`` still forces the pure-Python build (``--no-binary
  mypy``) and still pins mypy to exactly one version -- so the pin cannot drift
  back to a range that silently resolves to a compiled wheel with a
  binary-only dependency, which is precisely how the denial arrived;
* the installed mypy distribution is that pinned version;
* importing the typecheck runtime really works, and ``mypy.build`` -- the
  module whose native import was denied -- is genuinely loaded, so the check
  can never pass vacuously;
* every loaded ``mypy``/``mypyc``/``librt`` module is backed by a Python source
  file, never by a native extension. The extension suffixes cover Windows,
  Linux and macOS, so a POSIX CI run enforces the same property as the Windows
  worker.

Messages carry module names, distribution versions and file suffixes only;
never credentials, environment values or secret material.
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
# The distributions that make up the typecheck runtime itself. ``librt`` is
# listed because mypy 1.19+ imports it from ``mypy.build``; it must never
# appear as a loaded native module under the pinned, pure-Python runtime.
_RUNTIME_PACKAGES = frozenset({"mypy", "mypyc", "librt"})
# The canary module: its native import was the one the application-control
# policy denied, so a runtime that never loaded it proves nothing.
_REQUIRED_RUNTIME_MODULE = "mypy.build"
# Platform-independent on purpose: the same check must hold on the Windows
# worker and on a POSIX runner, so both native suffix families are rejected
# regardless of the host that runs the verification.
_NATIVE_SUFFIXES = tuple(sorted({*machinery.EXTENSION_SUFFIXES, ".pyd", ".so", ".dll"}))
# ``--no-binary mypy`` and ``--no-binary=mypy`` are both accepted pip spellings
# of the same directive; anything else is not the documented pin.
_NO_BINARY_RE = re.compile(r"(?m)^\s*--no-binary[\s=]+mypy\s*$")
_EXACT_PIN_RE = re.compile(r"(?m)^\s*mypy==([0-9][0-9A-Za-z.*+!-]*)\s*$")


class TypecheckRuntimeError(Exception):
    """Fail-closed typecheck-runtime condition; carries no secret material."""


def pinned_mypy_requirement(requirements_text: str) -> str:
    """The exact mypy version the requirements declare; fail closed otherwise.

    Both halves of the declaration are mandatory. Without ``--no-binary mypy``
    pip prefers the platform wheel, which is mypyc-compiled; without an exact
    pin the range can resolve forward into a release with a binary-only
    dependency. Either omission reintroduces the application-control exposure,
    so either omission fails closed here.
    """
    if _NO_BINARY_RE.search(requirements_text) is None:
        raise TypecheckRuntimeError(
            "requirements-dev.txt does not force the pure-Python mypy build "
            "(the `--no-binary mypy` directive is missing)."
        )
    pins = _EXACT_PIN_RE.findall(requirements_text)
    if len(pins) != 1:
        raise TypecheckRuntimeError(
            "requirements-dev.txt must pin mypy to exactly one version; found "
            f"{len(pins)} exact `mypy==` pin(s)."
        )
    return str(pins[0])


def native_runtime_modules(modules: Mapping[str, Any]) -> list[str]:
    """Loaded typecheck-runtime modules backed by a native extension file.

    A module without ``__file__`` (a namespace package) carries no code of its
    own and is therefore not a native module. Everything else is judged by its
    file suffix, which is what the loader -- and the application-control
    policy -- actually acts on.
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
    """Verify the declared pin, the installed version and the loaded runtime.

    Returns a short summary on success; raises ``TypecheckRuntimeError`` on any
    deviation. The three checks are deliberately independent: the declaration
    binds future installs, the installed version binds this environment, and
    the loaded-module inspection binds what the interpreter actually executed.
    """
    pinned = pinned_mypy_requirement(requirements_text)
    if installed_version != pinned:
        raise TypecheckRuntimeError(
            f"installed mypy {installed_version} is not the pinned {pinned}."
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
    return f"pure-Python mypy {pinned}; {verified} runtime module(s) verified as source-backed"


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
