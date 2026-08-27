"""Lokális, read-only reconciliation (Gate 8 reconciliation bizonyíték).

Kizárólag helyi, hálózatmentes, szintetikus egyeztetés; semmilyen távoli
vagy production írás nem történik. A script determinisztikusan összeveti:

1. a védett acceptance corpuszt az ADAS protected-corpus manifesttel (SHA-256);
2. a tracked-secret baseline integritását a kanonikus
   check_secret_baseline logikával (élő scan vs. a védett .secrets.baseline;
   a baseline-en kívüli jelölt kizárólag strukturális, a munkafából
   újraszármaztatott és fingerprinttel igazolt osztályozással tisztázható,
   commitolt allowlist/delta nélkül; stale-only eltérés dokumentált
   warning, minden osztályozatlan találat FAIL);
3. a SOURCE_LOCK kibocsátási rögzítést (alembic head = a migrációs gráf
   tényleges egyetlen feje; a teljes, kötelező top-level verziómező-készlet
   -- platform_version, application_version, partner_field_version,
   commercial_integration_version -- szigorú semver és a scriptben pinelt
   explicit várt érték szerint; release_date ISO-dátum);
4. a seed-modullistát egy kizárólag a script által épített, privát
   in-memory SQLite adatbázis regiszterével (az app engine/session
   soha nem kerül felhasználásra, a DATABASE_URL környezeti változót a
   script nem olvassa és nem írja);
5. az Alembic migrációs gráf egyetlen fejét.

Bármelyik eltérés nemnulla kilépési kóddal (fail-closed) zárul. Mindegyik
probe lefut akkor is, ha egy korábbi elbukott: egyetlen hiba sem takarhatja el
a többiek állítását (a titok-scan determinisztikus delta esetén a
SOURCE_LOCK/alembic/regiszter/migráció állítások akkor is kiértékelődnek és
jelentést kapnak). Az összesített kilépési kód csak akkor 0, ha mindegyik
probe átment.

Teszt-seam: a vizsgált artefaktumok útvonala, az elvárt alembic head és a
pinelt várt verzióértékek környezeti változóval felülírhatók (kizárólag
szintetikus fail-closed bizonyítékhoz); a pipeline mindig az alapértelmezett
repo-útvonalakat és várt értékeket használja, mert ezeket a változókat nem
állítja be. A titok-scanre NINCS snapshot vagy környezeti seam: a kanonikus
check_secret_baseline mindig az élő scannel egyeztet, a tesztek kizárólag
közvetlen pytest monkeypatch segítségével gyorsítják. A lock verzióértékei és
a scriptben pinelt várt értékek csak együtt, egy auditált commitban
mozoghatnak.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_APP_ROOT = _SCRIPT_DIR.parent
_REPO_ROOT = _APP_ROOT.parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_SCRIPT_DIR))

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault(
    "PLATFORM_RUNTIME_ROOT",
    str(Path(tempfile.gettempdir()) / f"iip_reconciliation_{os.getpid()}"),
)

import check_secret_baseline  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import ModuleRegistry  # noqa: E402
from app.seed import MODULES, seed_database  # noqa: E402

EXPECTED_HEAD = os.environ.get("II_RECON_EXPECTED_ALEMBIC_HEAD", "20260816_0072")
CORPUS_MANIFEST = Path(
    os.environ.get(
        "II_RECON_CORPUS_MANIFEST",
        str(_REPO_ROOT / ".imperial-adas" / "protected-corpus-manifest.json"),
    )
)
SECRETS_BASELINE = Path(
    os.environ.get("II_RECON_SECRETS_BASELINE", str(_REPO_ROOT / ".secrets.baseline"))
)
SOURCE_LOCK = Path(os.environ.get("II_RECON_SOURCE_LOCK", str(_APP_ROOT / "SOURCE_LOCK.json")))

_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# A SOURCE_LOCK szerződés teljes, kötelező top-level verziómező-készlete.
# Mindegyik mezőnek szerepelnie kell, stringnek és szigorú semvernek kell
# lennie, és exact egyeznie kell az alábbi pinelt várt értékkel; hiányzó,
# üres, rossz típusú, malformált vagy megváltoztatott érték fail-closed.
REQUIRED_LOCK_VERSION_FIELDS = (
    "platform_version",
    "application_version",
    "partner_field_version",
    "commercial_integration_version",
)
EXPECTED_LOCK_VERSIONS = {
    "platform_version": os.environ.get("II_RECON_EXPECTED_PLATFORM_VERSION", "5.0.0"),
    "application_version": os.environ.get("II_RECON_EXPECTED_APPLICATION_VERSION", "1.5.0"),
    "partner_field_version": os.environ.get("II_RECON_EXPECTED_PARTNER_FIELD_VERSION", "1.0.0"),
    "commercial_integration_version": os.environ.get(
        "II_RECON_EXPECTED_COMMERCIAL_INTEGRATION_VERSION", "1.0.0"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alembic_heads() -> list[str]:
    return ScriptDirectory.from_config(Config(str(_APP_ROOT / "alembic.ini"))).get_heads()


def _corpus_probe() -> None:
    if not CORPUS_MANIFEST.is_file():
        raise SystemExit(
            f"reconciliation FAIL: protected-corpus manifest hianyzik: {CORPUS_MANIFEST}"
        )
    manifest = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("reconciliation FAIL: a manifest 'files' listaja ures vagy ervenytelen.")
    for entry in entries:
        path = entry.get("path")
        expected = entry.get("sha256")
        if not path or not expected:
            raise SystemExit("reconciliation FAIL: manifest-bejegyzes path/sha256 nelkul.")
        target = _REPO_ROOT / path
        if not target.is_file():
            raise SystemExit(f"reconciliation FAIL: vedett corpuszfajl hianyzik: {path}")
        observed = _sha256(target)
        if observed != expected:
            raise SystemExit(
                f"reconciliation FAIL: corpusz-SHA elteres: {path} "
                f"{observed[:12]}... != {expected[:12]}..."
            )
    print(f"reconciliation PASS: vedett acceptance corpusz ({len(entries)} fajl) hash-egyezesben.")


def _secret_baseline_probe() -> None:
    # Nincs snapshot/környezeti seam: a kanonikus egyeztetés mindig az élő
    # scannel fut; a tesztek csak közvetlen monkeypatch-csel gyorsítanak.
    status, message = check_secret_baseline.reconcile_tracked_secrets(SECRETS_BASELINE)
    if status != 0:
        raise SystemExit(f"reconciliation FAIL: {message}")
    print(f"reconciliation PASS: tracked-secret baseline: {message}")


def _source_lock_probe() -> None:
    if not SOURCE_LOCK.is_file():
        raise SystemExit(f"reconciliation FAIL: SOURCE_LOCK hianyzik: {SOURCE_LOCK}")
    try:
        lock = json.loads(SOURCE_LOCK.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"reconciliation FAIL: a SOURCE_LOCK nem ertelmezheto JSON: {exc}"
        ) from exc
    heads = _alembic_heads()
    lock_head = lock.get("alembic_head")
    if heads != [lock_head]:
        raise SystemExit(
            "reconciliation FAIL: SOURCE_LOCK alembic_head "
            f"{lock_head!r} elter a migracios graf fejetol {heads!r}."
        )
    for key in REQUIRED_LOCK_VERSION_FIELDS:
        expected = EXPECTED_LOCK_VERSIONS[key]
        if not isinstance(expected, str) or not _SEMVER.fullmatch(expected):
            raise SystemExit(
                f"reconciliation FAIL: pinelt vart ertek {key} ervenytelen: {expected!r}."
            )
    for key in REQUIRED_LOCK_VERSION_FIELDS:
        value = lock.get(key)
        expected = EXPECTED_LOCK_VERSIONS[key]
        if not isinstance(value, str) or not _SEMVER.fullmatch(value):
            raise SystemExit(f"reconciliation FAIL: SOURCE_LOCK {key} ervenytelen: {value!r}.")
        if value != expected:
            raise SystemExit(
                f"reconciliation FAIL: SOURCE_LOCK {key} elter a pinelt "
                f"vart ertektol: {value!r} (vart: {expected!r})."
            )
    release_date = lock.get("release_date")
    if not isinstance(release_date, str) or not _ISO_DATE.fullmatch(release_date):
        raise SystemExit(
            f"reconciliation FAIL: SOURCE_LOCK release_date ervenytelen: {release_date!r}."
        )
    print(
        "reconciliation PASS: SOURCE_LOCK verziok rogzitve "
        f"(platform {lock['platform_version']}, app {lock['application_version']}, "
        f"partner_field {lock['partner_field_version']}, "
        f"commercial_integration {lock['commercial_integration_version']}, "
        f"alembic_head {lock_head})."
    )


def _registry_probe() -> None:
    # Privát, kizárólag a script által épített in-memory SQLite: nem az app
    # engine/SessionLocal, és a DATABASE_URL-t nem figyeli. Minden
    # create/drop/seed művelet csak erre az ephemeral motorra irányul.
    probe_engine = create_engine(
        "sqlite://",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    probe_session = sessionmaker(
        bind=probe_engine, autoflush=False, expire_on_commit=False, future=True
    )
    try:
        Base.metadata.drop_all(bind=probe_engine)
        Base.metadata.create_all(bind=probe_engine)
        with probe_session() as db:
            seed_database(db)
            keys = set(db.scalars(select(ModuleRegistry.module_key)).all())
    finally:
        probe_engine.dispose()
    expected = {module[0] for module in MODULES}
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise SystemExit(f"reconciliation FAIL: regiszter-elteres missing={missing} extra={extra}.")
    print(f"reconciliation PASS: modulregiszter ({len(keys)} modul) a seeddel egyezik.")


def _migration_probe() -> None:
    heads = _alembic_heads()
    if heads != [EXPECTED_HEAD]:
        raise SystemExit(f"reconciliation FAIL: alembic head {heads!r}, vart: {EXPECTED_HEAD}.")
    print(f"reconciliation PASS: pontosan egy alembic head ({EXPECTED_HEAD}).")


def main() -> int:
    # Aggregált kiértékelés: minden probe lefut, az elbukottak üzenete a
    # stderr-re kerül; az összesített kód csak akkor 0, ha mindegyik átment.
    probes = (
        _corpus_probe,
        _secret_baseline_probe,
        _source_lock_probe,
        _registry_probe,
        _migration_probe,
    )
    failures = 0
    for probe in probes:
        try:
            probe()
        except SystemExit as exc:
            print(str(exc), file=sys.stderr)
            failures += 1
        except Exception as exc:  # noqa: BLE001 - fail-closed, nem maszkolhat
            # Váratlan hiba (pl. malformált manifest JSON) sem takarhatja el a
            # többi probe állítását: megnevezve, fail-closed módon számoljuk.
            print(
                f"reconciliation FAIL: {probe.__name__} varatlan hiba: {exc.__class__.__name__}.",
                file=sys.stderr,
            )
            failures += 1
    if failures:
        print(
            f"reconciliation FAIL: {failures} probe(s) sikertelen (fail-closed).",
            file=sys.stderr,
        )
        return 1
    print("reconciliation PASS: minden lokalis, szintetikus egyeztetes sikeres.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass
    raise SystemExit(main())
