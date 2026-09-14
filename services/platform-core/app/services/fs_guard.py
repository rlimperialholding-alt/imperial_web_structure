"""Fail-closed fájlrendszer-konténment (path injection elleni védelem).

Felhasználói vagy providerből származó útvonalkomponens csak akkor érhet
fájlrendszer-műveletet, ha:

1. minden komponens szigorú karakterosztály-validáción ment át (traversal,
   abszolút útvonal, alternatív szeparátor már itt elbukik), és
2. a kanonikus feloldás (``os.path.realpath``, szimbolikus link és junction
   követésével) után a cél az engedélyezett gyökér alatt marad
   (containment-ellenőrzés a feloldott útvonalon, nem a nyers stringen).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MAX_SEGMENT_LENGTH = 64


def safe_segment(value: object, *, label: str = "azonosító") -> str:
    """Egyetlen útvonalkomponens validálása: alfanumerikus kezdet, csak
    betű, számjegy, pont, aláhúzás, kötőjel; maximális hossz 64 karakter."""
    if not isinstance(value, str) or not value or len(value) > MAX_SEGMENT_LENGTH:
        raise ValueError(f"Érvénytelen {label}.")
    if _SEGMENT_RE.fullmatch(value) is None:
        raise ValueError(f"Érvénytelen {label}.")
    return value


def contained_path(root: str | Path, *segments: str) -> Path:
    """Validált komponensekből épített, kanonikusan a gyökér alatt maradó útvonal.

    A feloldás után futó ``startswith`` ellenőrzés a CodeQL által elvárt
    normpath/realpath + prefix mintát követi; szimbolikus linken vagy junctionön
    át történő kilépésnél a függvény hibával leáll (fail-closed).
    """
    if not segments:
        raise ValueError("Legalább egy útvonalkomponens kötelező.")
    base = os.path.realpath(str(root))
    candidate = os.path.realpath(
        os.path.join(base, *(safe_segment(segment) for segment in segments))
    )
    if candidate != base and not candidate.startswith(base + os.sep):
        raise ValueError("A célútvonal az engedélyezett gyökéren kívülre mutat.")
    return Path(candidate)


def require_contained(root: str | Path, candidate: str | Path) -> Path:
    """Egy létező (például providerből kapott) útvonal konténment-ellenőrzése.

    A nyers útvonalat kanonikus feloldás után a gyökérhez mérjük; a gyökéren
    kívül eső vagy nem létező útvonal hibát ad (fail-closed).
    """
    base = os.path.realpath(str(root))
    resolved = os.path.realpath(str(candidate))
    if resolved != base and not resolved.startswith(base + os.sep):
        raise ValueError("Az útvonal az engedélyezett gyökéren kívülre mutat.")
    return Path(resolved)
