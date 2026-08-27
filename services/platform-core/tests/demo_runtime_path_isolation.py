"""Reversible, unconditional runtime-path isolation for the test suite.

The platform-core suite must always write demo runtime state under its own
pytest temporary root. Two runtime state files are covered:

* the cross-module UAT sandbox (``DEMO_RUNTIME_PATH``,
  ``data/platform_demo_runtime.json`` by default), and
* the synthetic demo-credential state shared between processes
  (``DEMO_CREDENTIALS_STATE_PATH``, the git-ignored
  ``runtime/demo-credentials-state.json`` by default; seed.py reads the
  variable at import time).

Both isolations are *unconditional* assignments (not ``setdefault``), so an
ambient variable can never redirect test writes outside the temporary root;
the previous values are saved and restored at session end, keeping the
environment change reversible and test-scoped.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "DEMO_RUNTIME_PATH"
CREDENTIALS_ENV_VAR = "DEMO_CREDENTIALS_STATE_PATH"


def isolate_demo_runtime_path(temp_root: Path) -> tuple[str | None, str]:
    """Force the demo runtime path under *temp_root*.

    Returns ``(previous_value, isolated_value)``; the caller is expected to
    pass *previous_value* to :func:`restore_demo_runtime_path` when the test
    scope ends.
    """
    previous = os.environ.get(ENV_VAR)
    isolated = str(temp_root / "demo" / "platform_demo_runtime.json")
    os.environ[ENV_VAR] = isolated
    return previous, isolated


def restore_demo_runtime_path(previous: str | None) -> None:
    """Undo :func:`isolate_demo_runtime_path` for *previous*."""
    if previous is None:
        os.environ.pop(ENV_VAR, None)
    else:
        os.environ[ENV_VAR] = previous


def isolate_demo_credentials_state_path(temp_root: Path) -> tuple[str | None, str]:
    """Force the demo-credential state path under *temp_root*.

    Without this isolation the suite would write the real repository
    ``services/platform-core/runtime/demo-credentials-state.json`` on the
    first seed import, and a leftover operator override could leak into the
    session. Returns ``(previous_value, isolated_value)`` for the matching
    :func:`restore_demo_credentials_state_path`.
    """
    previous = os.environ.get(CREDENTIALS_ENV_VAR)
    isolated = str(temp_root / "demo" / "demo-credentials-state.json")
    os.environ[CREDENTIALS_ENV_VAR] = isolated
    return previous, isolated


def restore_demo_credentials_state_path(previous: str | None) -> None:
    """Undo :func:`isolate_demo_credentials_state_path` for *previous*."""
    if previous is None:
        os.environ.pop(CREDENTIALS_ENV_VAR, None)
    else:
        os.environ[CREDENTIALS_ENV_VAR] = previous
