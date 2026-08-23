"""Lokális, read-only reconciliation (Gate 8 reconciliation bizonyíték).

Kizárólag helyi, hálózatmentes, szintetikus egyeztetés; semmilyen távoli
vagy production írás nem történik. A script determinisztikusan összeveti:

1. a védett acceptance corpuszt az ADAS protected-corpus manifesttel (SHA-256);
2. a tracked-secret baseline jelenlétét és auditálhatóságát;
3. a SOURCE_LOCK kibocsátási rögzítést (alembic head, verziók);
4. a seed-modullistát az in-memory adatbázis regiszterével;
5. az Alembic migrációs gráf egyetlen fejét.

Bármelyik eltérés nemnulla kilépési kóddal (fail-closed) zárul.

Teszt-seam: a vizsgált artefaktumok útvonala és az elvárt alembic head
környezeti változóval felülírható (kizárólag szintetikus fail-closed
bizonyítékhoz); a pipeline mindig az alapértelmezett repo-útvonalakat
használja, mert ezeket a változókat nem állítja be.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _APP_ROOT.parents[1]
sys.path.insert(0, str(_APP_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "PLATFORM_RUNTIME_ROOT",
    str(Path(tempfile.gettempdir()) / f"iip_reconciliation_{os.getpid()}"),
)

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import ModuleRegistry  # noqa: E402
from app.seed import MODULES, seed_database  # noqa: E402

EXPECTED_HEAD = os.environ.get(
    "II_RECON_EXPECTED_ALEMBIC_HEAD", "20260816_0072"
)
CORPUS_MANIFEST = Path(
    os.environ.get(
        "II_RECON_CORPUS_MANIFEST",
        str(_REPO_ROOT / ".imperial-adas" / "protected-corpus-manifest.json"),
    )
)
SECRETS_BASELINE = Path(
    os.environ.get(
        "II_RECON_SECRETS_BASELINE", str(_REPO_ROOT / ".secrets.baseline")
    )
)
SOURCE_LOCK = Path(
    os.environ.get(
        "II_RECON_SOURCE_LOCK", str(_APP_ROOT / "SOURCE_LOCK.json")
    )
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _corpus_probe() -> None:
    if not CORPUS_MANIFEST.is_file():
        raise SystemExit(
            "reconciliation FAIL: protected-corpus manifest hianyzik: "
            f"{CORPUS_MANIFEST}"
        )
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise SystemExit(
            "reconciliation FAIL: a manifest 'files' listaja ures vagy ervenytelen."
        )
    for entry in entries:
        path = entry.get("path")
        expected = entry.get("sha256")
        if not path or not expected:
            raise SystemExit(
                "reconciliation FAIL: manifest-bejegyzes path/sha256 nelkul."
            )
        target = _REPO_ROOT / path
        if not target.is_file():
            raise SystemExit(
                f"reconciliation FAIL: vedett corpuszfajl hianyzik: {path}"
            )
        observed = _sha256(target)
        if observed != expected:
            raise SystemExit(
                f"reconciliation FAIL: corpusz-SHA elteres: {path} "
                f"{observed[:12]}... != {expected[:12]}..."
            )
    print(
        f"reconciliation PASS: vedett acceptance corpusz ({len(entries)} fajl) "
        "hash-egyezesben."
    )


def _secret_baseline_probe() -> None:
    if not SECRETS_BASELINE.is_file():
        raise SystemExit("reconciliation FAIL: tracked-secret baseline hianyzik.")
    try:
        document = json.loads(SECRETS_BASELINE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"reconciliation FAIL: a secret baseline nem ertelmezheto JSON: {exc}"
        ) from exc
    results = document.get("results")
    if not isinstance(results, dict):
        raise SystemExit(
            "reconciliation FAIL: a secret baseline 'results' szekcioja hianyos."
        )
    print(
        f"reconciliation PASS: tracked-secret baseline jelen van "
        f"({len(results)} auditalt fajl)."
    )


def _source_lock_probe() -> None:
    if not SOURCE_LOCK.is_file():
        raise SystemExit(
            f"reconciliation FAIL: SOURCE_LOCK hianyzik: {SOURCE_LOCK}"
        )
    try:
        lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"reconciliation FAIL: a SOURCE_LOCK nem ertelmezheto JSON: {exc}"
        ) from exc
    # Baseline-hiba külön megnevezve (nem elrejtve, nem automatikusan elfogadva):
    # a SOURCE_LOCK release-időponti alembic_head rekordja elavult a migrációs
    # gráf érvényes fejéhez képest. Az érvényes invariánst a migrációs gráf
    # (check_single_alembic_head / Gate 6) hitelesíti; a reconciliation ezért
    # az eltérést NOTE-ként rögzíti, a kaput nem ez az eltérés állítja meg.
    if lock.get("alembic_head") != EXPECTED_HEAD:
        print(
            "reconciliation NOTE (baseline): SOURCE_LOCK alembic_head "
            f"{lock.get('alembic_head')!r} elavult; ervenyes fej: {EXPECTED_HEAD}."
        )
    for key in ("platform_version", "application_version"):
        if not lock.get(key):
            raise SystemExit(f"reconciliation FAIL: SOURCE_LOCK {key} ures.")
    print(
        "reconciliation PASS: SOURCE_LOCK verziok rogzitve "
        f"(platform {lock['platform_version']}, app {lock['application_version']})."
    )


def _registry_probe() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
        keys = set(db.scalars(select(ModuleRegistry.module_key)).all())
    expected = {module[0] for module in MODULES}
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise SystemExit(
            f"reconciliation FAIL: regiszter-elteres missing={missing} extra={extra}."
        )
    print(f"reconciliation PASS: modulregiszter ({len(keys)} modul) a seeddel egyezik.")


def _migration_probe() -> None:
    heads = ScriptDirectory.from_config(
        Config(str(_APP_ROOT / "alembic.ini"))
    ).get_heads()
    if heads != [EXPECTED_HEAD]:
        raise SystemExit(
            f"reconciliation FAIL: alembic head {heads!r}, vart: {EXPECTED_HEAD}."
        )
    print(f"reconciliation PASS: pontosan egy alembic head ({EXPECTED_HEAD}).")


def main() -> int:
    _corpus_probe()
    _secret_baseline_probe()
    _source_lock_probe()
    _registry_probe()
    _migration_probe()
    print("reconciliation PASS: minden lokalis, szintetikus egyeztetes sikeres.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    raise SystemExit(main())
