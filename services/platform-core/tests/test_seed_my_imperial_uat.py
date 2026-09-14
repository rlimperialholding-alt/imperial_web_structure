"""Célzott regresszió a Task60 review által jelzett seed-hibára.

A `scripts/seed_my_imperial_uat.py` döntés-számlálója
``select(func.count())`` lekérdezést használ; a Task60 elutasított
jelöltje ezt a ``func`` import nélkül vezette be (NameError futásidőben).
Ez a teszt a korrigált szkript teljes ``main()`` útját futtatja a
tesztadatbázison, és rögzíti:

- az import/lekérdezés fut (nincs NameError),
- a döntés- és frissítésszám a tényleges, újra-futtatáskor is stabil
  (idempens seed) érték.
"""

from __future__ import annotations

import ast
from contextlib import redirect_stdout
from io import StringIO

from scripts.seed_my_imperial_uat import CUSTOMER_EMAIL, PROJECT_ID, main


def _run_main() -> dict:
    buffer = StringIO()
    with redirect_stdout(buffer):
        main()
    payload = ast.literal_eval(buffer.getvalue())
    assert isinstance(payload, dict)
    return payload


def test_seed_my_imperial_uat_decision_count_uses_func_import_and_runs() -> None:
    first = _run_main()
    assert first["project_id"] == PROJECT_ID
    assert first["customer_email"] == CUSTOMER_EMAIL
    assert first["decisions"] == 1
    assert first["updates"] >= 1


def test_seed_my_imperial_uat_is_idempotent_across_reruns() -> None:
    first = _run_main()
    second = _run_main()
    assert second == first
