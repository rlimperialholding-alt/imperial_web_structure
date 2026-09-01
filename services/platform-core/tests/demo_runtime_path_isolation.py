"""Reversible, unconditional runtime-path isolation for the test suite."""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "DEMO_RUNTIME_PATH"
CREDENTIALS_ENV_VAR = "DEMO_CREDENTIALS_STATE_PATH"


def _isolate(temp_root: Path, env_var: str, filename: str) -> tuple[str | None, str]:
    """Force the state file under *temp_root*; returns ``(previous, isolated)``."""
    previous = os.environ.get(env_var)
    isolated = str(temp_root / "demo" / filename)
    os.environ[env_var] = isolated
    return previous, isolated


def _restore(env_var: str, previous: str | None) -> None:
    """Undo an isolation for *previous*; ``None`` pops the variable."""
    if previous is None:
        os.environ.pop(env_var, None)
    else:
        os.environ[env_var] = previous


def isolate_demo_runtime_path(temp_root: Path) -> tuple[str | None, str]:
    """Force the demo runtime path under *temp_root*."""
    return _isolate(temp_root, ENV_VAR, "platform_demo_runtime.json")


def restore_demo_runtime_path(previous: str | None) -> None:
    """Undo :func:`isolate_demo_runtime_path` for *previous*."""
    _restore(ENV_VAR, previous)


def isolate_demo_credentials_state_path(temp_root: Path) -> tuple[str | None, str]:
    """Force the demo-credential state path under *temp_root*."""
    return _isolate(temp_root, CREDENTIALS_ENV_VAR, "demo-credentials-state.json")


def restore_demo_credentials_state_path(previous: str | None) -> None:
    """Undo :func:`isolate_demo_credentials_state_path` for *previous*."""
    _restore(CREDENTIALS_ENV_VAR, previous)
