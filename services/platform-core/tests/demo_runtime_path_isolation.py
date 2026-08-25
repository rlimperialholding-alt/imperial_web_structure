"""Reversible, unconditional demo-runtime path isolation for the test suite.

The platform-core suite must always write demo runtime state under its own
pytest temporary root. The isolation is an *unconditional* assignment (not
``setdefault``), so an ambient ``DEMO_RUNTIME_PATH`` can never redirect test
writes outside the temporary root; the previous value is saved and restored
at session end, keeping the environment change reversible and test-scoped.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "DEMO_RUNTIME_PATH"


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
