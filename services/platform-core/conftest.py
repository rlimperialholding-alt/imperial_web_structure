"""Test-path bridge for the unchanged canonical Contract Generator v0.4 package.

The canonical source tree is vendored byte-for-byte under integrations/.  This
bridge exposes its original top-level package name to its own untouched tests;
it does not alter the canonical source or business logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CANONICAL_CONTRACT_ROOT = ROOT / "integrations" / "contract_generator_v0_4"
for path in (ROOT, CANONICAL_CONTRACT_ROOT):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)
