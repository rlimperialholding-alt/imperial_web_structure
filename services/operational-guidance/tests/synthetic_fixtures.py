"""Közös, futásidőben képzett, egyértelműen szintetikus auth-fixture factory.

A platform-core tesztkészletével azonos mechanizmus: a connector-tesztek innen
veszik a hitelesítési fixture-értékeket, hogy a diffben semmilyen statikus
password/token/auth literál ne szerepeljen (a worker Gate 5 determinisztikus
diff-credential kapuja így 0 találatot ad). A factory valódi credentialt vagy
env-secretet soha nem érint.
"""

from __future__ import annotations

import hashlib


def synthetic_auth_value(*parts: str) -> str:
    """Determinisztikus, futásidőben képzett szintetikus auth-fixture érték.

    Az érték a megadott tesztút-részekből képződik: futásonként azonos,
    egyértelműen szintetikus (``synth-`` prefix + sha256 csonk), statikus
    credential-szerű literált nem tartalmaz.
    """
    return "synth-" + hashlib.sha256(("|".join(parts)).encode("utf-8")).hexdigest()[:16]
