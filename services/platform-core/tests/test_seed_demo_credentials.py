"""A szintetikus demo-belépés forrás- és production-kapu regressziója.

Task34 review-remediation: a korábbi, részekből újraösszerakható fix demo
érték helyett a forrásban semmilyen rekonstruálható credential NINCS. Az érték
vagy a CONTROL_CENTER_DEMO_LOGIN környezeti változóból érkezik (default
nélkül), vagy futásonként/telepítésenként biztonságosan generált, egyedi
véletlen érték. A production felhasználást nem a konstrukció, hanem a
`demo_accounts_allowed()` fail-closed kapu zárja ki. A találatot tilos
auditbesorolással elrejteni, ezért ez a modul közvetlenül a forrásra és a
tényleges seed-viselkedésre állít.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app import seed
from app.models import PartnerFieldAccess, PartnerWorker, User
from app.security import verify_password
from app.seed import (
    DEMO_CREDENTIALS_STATE_ENV,
    DEMO_LOGIN_ENV,
    DEMO_PARTNER_CODE,
    DEMO_PARTNER_CODE_ENV,
    DEMO_PASSWORD,
    DEMO_PASSWORD_HASH,
    demo_accounts_allowed,
    demo_login_value,
    demo_partner_code,
    demo_runtime_credentials,
    seed_database,
)

SEED_SOURCE = Path(seed.__file__).read_text(encoding="utf-8")
# `password = "..."`, `secret: "..."` és társai: a beégetett, credential alakú
# értékek detektorral egyező, szűk mintája.
_CREDENTIAL_LITERAL = re.compile(
    r"(?i)\b\w*(?:password|passwd|secret|token|api_key|apikey)\w*\s*[:=]\s*"
    r"[\"'][^\"'\n]{4,}[\"']"
)
_URLSAFE = re.compile(r"^[A-Za-z0-9_-]+$")
# Szintetikus, credential-alak nélküli sentinel a stale hash szimulálásához.
STALE_HASH = "stale-hash"


def _production_settings(**overrides):
    return dataclasses.replace(seed.settings, environment="production", **overrides)


class TestSeedSourceHasNoCredentialLiteral:
    """A `Secret Keyword` találat forrásoldali megszűnésének bizonyítéka."""

    def test_no_credential_shaped_literal_in_seed_source(self) -> None:
        assert _CREDENTIAL_LITERAL.findall(SEED_SOURCE) == []

    def test_effective_demo_value_is_not_a_contiguous_source_literal(self) -> None:
        assert DEMO_PASSWORD not in SEED_SOURCE

    def test_demo_value_is_generated_per_process_and_never_blank(self) -> None:
        # A futásonkénti érték formája és hossza a dokumentált
        # secrets.token_urlsafe(18) szerződés (24 karakter, URL-safe betűk).
        assert len(DEMO_PASSWORD) == 24
        assert _URLSAFE.fullmatch(DEMO_PASSWORD)

    def test_generated_value_is_unique_per_run(self) -> None:
        # Két üres környezetből származó generálás nem adhatja vissza ugyanazt
        # a fix értéket: az egyediség maga a biztonsági szerződés.
        first = demo_login_value({})
        second = demo_login_value({})
        assert first != second
        assert len(first) == len(second) == 24

    def test_environment_override_replaces_the_generated_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEMO_LOGIN_ENV, "operator-supplied-demo-value")
        assert demo_login_value() == "operator-supplied-demo-value"

    def test_blank_override_falls_back_to_a_generated_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEMO_LOGIN_ENV, "   ")
        value = demo_login_value()
        assert value != "operator-supplied-demo-value"
        assert len(value) == 24
        assert _URLSAFE.fullmatch(value)

    def test_explicit_environ_mapping_takes_precedence_over_ambient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEMO_LOGIN_ENV, "ambient-value")
        assert demo_login_value({DEMO_LOGIN_ENV: "mapped-value"}) == "mapped-value"


class TestPartnerDemoCodeSourceHasNoFixedLiteral:
    """A korábbi fix partneri demókód forrásoldali megszűnésének bizonyítéka."""

    def test_no_quoted_partner_code_literal_in_seed_source(self) -> None:
        # A futásidejű érték idézőjelek közötti literálként sehol sem lehet a
        # forrásban (a korábbi fix kód hash_password("...") alakban állt ott).
        assert f'"{DEMO_PARTNER_CODE}"' not in SEED_SOURCE

    def test_previous_fixed_partner_code_is_absent_from_seed_source(self) -> None:
        # A korábbi, ismert fix demókód semmilyen formában nem maradhat.
        assert "654321" not in SEED_SOURCE

    def test_partner_code_is_generated_per_process_and_matches_the_ui_contract(self) -> None:
        # A futásonkénti érték hatjegyű numerikus: a belépő oldal numerikus
        # beviteli szerződését (inputmode=numeric, minlength=6) őrzi meg.
        assert re.fullmatch(r"[0-9]{6}", DEMO_PARTNER_CODE)

    def test_generated_partner_code_is_unique_per_run(self) -> None:
        first = demo_partner_code({})
        second = demo_partner_code({})
        assert first != second
        assert re.fullmatch(r"[0-9]{6}", first)
        assert re.fullmatch(r"[0-9]{6}", second)

    def test_partner_code_environment_override_replaces_the_generated_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEMO_PARTNER_CODE_ENV, "operator-supplied-partner-code")
        assert demo_partner_code() == "operator-supplied-partner-code"

    def test_blank_partner_code_override_falls_back_to_a_generated_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(DEMO_PARTNER_CODE_ENV, "  ")
        value = demo_partner_code()
        assert value != "operator-supplied-partner-code"
        assert re.fullmatch(r"[0-9]{6}", value)

    def test_partner_login_template_has_no_fixed_demo_code_literal(self, client) -> None:
        """A belépő oldal nem írhat ki forrásból rekonstruálható fix kódot.

        Nem-production módban a futásidejű érték jelenik meg; a korábbi fix
        literál semmilyen formában nem szerepelhet a kimenetben.
        """
        response = client.get("/partner-field/login")
        assert response.status_code == 200
        assert DEMO_PARTNER_CODE in response.text
        assert "654321" not in response.text


class TestDemoSeedKeepsStoredHashesInSync:
    """A futásonkénti érték változhat; a seed a tárolt hash-t követi."""

    def test_reseed_refreshes_existing_demo_user_hash_to_process_value(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            seed, "settings", dataclasses.replace(seed.settings, environment="development")
        )
        owner = db.scalar(select(User).where(User.email == "owner@imperial.local"))
        assert owner is not None, "a fixture-nek demo fiókot kell létrehoznia"
        owner.password_hash = STALE_HASH
        db.flush()

        seed_database(db)
        db.flush()

        refreshed = db.scalar(select(User).where(User.email == "owner@imperial.local"))
        assert refreshed is not None
        assert refreshed.password_hash == DEMO_PASSWORD_HASH
        assert refreshed.password_hash != STALE_HASH


class TestDemoCredentialsRuntimeState:
    """A demo-belépés közös, nem követett futásidejű állapota.

    Többfolyamatos és újraindítás utáni konzisztencia: a generált demo
    login és partner-kód a közös (git-ignored) állapotfájlban él, minden
    írás után visszaolvasásra kerül, így a seedelő és a login oldalt
    renderelő folyamat garantáltan ugyanazt az értéket látja.
    """

    def test_shared_state_makes_values_stable_across_processes(self, tmp_path: Path) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        first = demo_runtime_credentials({}, state_path=state_path)
        # Második "folyamat": üres környezet, ugyanaz a közös állapotfájl.
        second = demo_runtime_credentials({}, state_path=state_path)
        assert first == second
        assert state_path.is_file()
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert document["demoLogin"] == first[0]
        assert document["demoPartnerCode"] == first[1]
        assert len(first[0]) == 24
        assert re.fullmatch(r"[0-9]{6}", first[1])

    def test_existing_state_is_authoritative_without_rewrite(self, tmp_path: Path) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        demo_runtime_credentials(
            {
                DEMO_LOGIN_ENV: "operator-supplied-demo-value",
                DEMO_PARTNER_CODE_ENV: "112233",
            },
            state_path=state_path,
        )
        before = state_path.read_text(encoding="utf-8")
        resolved = demo_runtime_credentials({}, state_path=state_path)
        assert resolved == ("operator-supplied-demo-value", "112233")
        assert state_path.read_text(encoding="utf-8") == before

    def test_environment_override_replaces_and_persists(self, tmp_path: Path) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        demo_runtime_credentials({}, state_path=state_path)
        overridden = demo_runtime_credentials(
            {DEMO_LOGIN_ENV: "new-operator-value"}, state_path=state_path
        )
        assert overridden[0] == "new-operator-value"
        # A többi folyamat (env override nélkül) is az override-olt értéket
        # látja: az override a közös állapotba íródik.
        assert demo_runtime_credentials({}, state_path=state_path) == overridden

    def test_corrupt_state_falls_back_to_generated_values(self, tmp_path: Path) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        state_path.write_text("{not valid json", encoding="utf-8")
        resolved = demo_runtime_credentials({}, state_path=state_path)
        assert len(resolved[0]) == 24
        assert re.fullmatch(r"[0-9]{6}", resolved[1])
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert document["demoLogin"] == resolved[0]
        assert document["demoPartnerCode"] == resolved[1]

    def test_non_string_or_missing_state_fields_are_rejected(self, tmp_path: Path) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        state_path.write_text(
            json.dumps({"demoLogin": 123, "demoPartnerCode": "112233"}),
            encoding="utf-8",
        )
        assert seed._read_demo_credentials_state(state_path) is None
        state_path.write_text(json.dumps(["demoLogin", "demoPartnerCode"]), encoding="utf-8")
        assert seed._read_demo_credentials_state(state_path) is None
        state_path.write_text(
            json.dumps({"demoLogin": "", "demoPartnerCode": "112233"}),
            encoding="utf-8",
        )
        assert seed._read_demo_credentials_state(state_path) is None
        assert seed._read_demo_credentials_state(tmp_path / "missing.json") is None
        state_path.write_text(
            json.dumps({"demoLogin": "ok-login", "demoPartnerCode": "112233"}),
            encoding="utf-8",
        )
        assert seed._read_demo_credentials_state(state_path) == ("ok-login", "112233")

    def test_default_state_path_lives_in_the_git_ignored_runtime_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DEMO_CREDENTIALS_STATE_ENV, raising=False)
        path = seed._demo_credentials_state_path()
        assert "runtime" in path.parts
        assert path.name == "demo-credentials-state.json"
        # A teljes runtime könyvtár git-ignored, tehát a plaintext demo
        # értékek soha nem kerülhetnek tracked fájlba.
        repo_root = Path(seed.__file__).resolve().parents[3]
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=str(repo_root),
            capture_output=True,
        ).returncode
        assert ignored == 0

    def test_production_credentials_never_touch_the_shared_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        monkeypatch.delenv(DEMO_LOGIN_ENV, raising=False)
        monkeypatch.delenv(DEMO_PARTNER_CODE_ENV, raising=False)
        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        monkeypatch.setattr(seed, "_demo_credentials_state_path", lambda: state_path)
        login, partner = seed._process_demo_credentials()
        assert not state_path.exists()
        assert len(login) == 24
        assert re.fullmatch(r"[0-9]{6}", partner)


class TestDemoCredentialsConcurrentCreation:
    """Valódi többfolyamatos verseny az első állapotlétrehozásra.

    A Task36 review HIGH közvetlen regressziója: korábban két egyidejű
    folyamat is üres állapotot olvashatott, különböző értékeket
    generálhatott és mindkettő írhatott -- az exclusive-create
    lock-protokollal pontosan egy folyamat generál és persistál, a többi a
    persistált állapothoz konvergál, újraindítás után is. Minden alfolyamat
    valódi OS-folyamat, amely a tényleges ``app.seed`` modult importálja (az
    import maga futtatja a megosztott állapot létrehozását), nem szál- vagy
    folyamat-szimuláció. A worker kód nem tartalmaz semmilyen credential
    alakú literált, a plaintext demo érték kizárólag a tmp_path alatti
    állapotfájlban és a folyamatok stdoutján (memóriában) jelenik meg --
    tracked forrásba, logba vagy proofba soha.
    """

    @staticmethod
    def _worker_code() -> str:
        return (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from app import seed\n"
            "print(seed.DEMO_PASSWORD)\n"
            "print(seed.DEMO_PARTNER_CODE)\n"
        )

    @staticmethod
    def _spawn_workers(state_path: Path, count: int) -> list[subprocess.Popen[str]]:
        platform_core = Path(seed.__file__).resolve().parents[1]
        env = {**os.environ, DEMO_CREDENTIALS_STATE_ENV: str(state_path)}
        return [
            subprocess.Popen(
                [sys.executable, "-c", TestDemoCredentialsConcurrentCreation._worker_code(),
                 str(platform_core)],
                cwd=str(platform_core),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for _ in range(count)
        ]

    @staticmethod
    def _collect(processes: list[subprocess.Popen[str]]) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=300)
            assert process.returncode == 0, stderr
            lines = stdout.splitlines()
            assert len(lines) == 2, stdout
            results.append((lines[0], lines[1]))
        return results

    def test_concurrent_first_creation_converges_and_restarts_stably(
        self, tmp_path: Path
    ) -> None:
        """Négy egyidejű folyamat, egyetlen konvergens állapot, restart-stabilitás."""
        state_path = tmp_path / "demo-credentials-state.json"
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        results = self._collect(self._spawn_workers(state_path, count=4))
        # Mind a négy folyamat ugyanazt a párt látta:
        assert len(set(results)) == 1, results
        login, partner = results[0]
        assert len(login) == 24
        assert _URLSAFE.fullmatch(login)
        assert re.fullmatch(r"[0-9]{6}", partner)
        # A persistált állapot pontosan a konvergens érték:
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (login, partner)
        assert document["kind"] == "demo-credentials-runtime-state"
        # A creation-lock minden folyamat után felszabadult:
        assert not lock_path.exists()
        # Újraindítás-stabilitás: egy későbbi, egyedüli folyamat ugyanazt kapja.
        restart = self._collect(self._spawn_workers(state_path, count=1))
        assert restart == [(login, partner)]
        # A valódi repository munkafa nem piszkolódott: a plaintext demo érték
        # kizárólag a tmp_path alatti, nem követett állapotfájlban él.
        repo_root = Path(seed.__file__).resolve().parents[3]
        status_output = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(repo_root),
            text=True,
            encoding="utf-8",
        )
        assert "demo-credentials-state" not in status_output
        assert login not in status_output

    def test_fresh_creation_after_state_removal_converges_again(self, tmp_path: Path) -> None:
        """Az állapot törlése után egy új verseny ismét egyetlen értékre konvergál."""
        state_path = tmp_path / "demo-credentials-state.json"
        first = self._collect(self._spawn_workers(state_path, count=1))[0]
        state_path.unlink()
        results = self._collect(self._spawn_workers(state_path, count=4))
        assert len(set(results)) == 1, results
        login, partner = results[0]
        assert (login, partner) != first, "az új verseny friss értéket generált"
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (login, partner)

    def test_corrupt_state_self_heals_under_concurrent_creation(self, tmp_path: Path) -> None:
        """Sérült állapot mellett is egyetlen folyamat gyógyít, mindenki konvergál."""
        state_path = tmp_path / "demo-credentials-state.json"
        state_path.write_text("{not valid json", encoding="utf-8")
        results = self._collect(self._spawn_workers(state_path, count=3))
        assert len(set(results)) == 1, results
        login, partner = results[0]
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (login, partner)
        assert document["kind"] == "demo-credentials-runtime-state"

    def test_creation_lock_is_exclusive_and_reentrant_after_release(
        self, tmp_path: Path
    ) -> None:
        """Az exclusive-create lock pontosan egy folyamatnak jár egyszerre."""
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        assert seed._try_create_demo_state_lock(lock_path) is True
        assert seed._try_create_demo_state_lock(lock_path) is False
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
        seed._release_demo_state_lock(lock_path)
        assert not lock_path.exists()
        assert seed._try_create_demo_state_lock(lock_path) is True
        seed._release_demo_state_lock(lock_path)

    def test_held_lock_fails_closed_within_the_bounded_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tartósan fogott lock: korlátos várakozás után fail-closed hiba."""
        state_path = tmp_path / "demo-credentials-state.json"
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        assert seed._try_create_demo_state_lock(lock_path) is True
        monkeypatch.setattr(seed, "_DEMO_STATE_LOCK_RETRY_DELAYS", (0.01, 0.01, 0.01))
        try:
            with pytest.raises(seed.DemoCredentialsStateError):
                demo_runtime_credentials({}, state_path=state_path)
            # A várakozás alatt nem jött létre divergens állapot:
            assert not state_path.exists()
        finally:
            seed._release_demo_state_lock(lock_path)
        # A lock felszabadulása után a generálás rendben lefut:
        resolved = demo_runtime_credentials({}, state_path=state_path)
        assert len(resolved[0]) == 24
        assert re.fullmatch(r"[0-9]{6}", resolved[1])

    def test_unsafe_state_target_fails_closed(self, tmp_path: Path) -> None:
        """Könyvtár a state vagy lock útvonalon: fail-closed, nem öngyógyítás."""
        state_path = tmp_path / "demo-credentials-state.json"
        state_path.mkdir()
        with pytest.raises(seed.DemoCredentialsStateError):
            demo_runtime_credentials({}, state_path=state_path)
        state_path.rmdir()
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        lock_path.mkdir()
        with pytest.raises(seed.DemoCredentialsStateError):
            demo_runtime_credentials({}, state_path=state_path)

    def test_symlinked_state_target_fails_closed(self, tmp_path: Path) -> None:
        """Szimlink a state útvonalon: fail-closed átirányítás-védelem."""
        state_path = tmp_path / "demo-credentials-state.json"
        target = tmp_path / "elsewhere.json"
        try:
            state_path.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable on this host")
        with pytest.raises(seed.DemoCredentialsStateError):
            demo_runtime_credentials({}, state_path=state_path)


class TestPartnerDemoAccessGate:
    """A szintetikus partneri terepi hozzáférés production kapuja és reseed
    hash-szinkronja."""

    def test_seed_creates_partner_access_with_current_demo_code_hash(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            seed, "settings", dataclasses.replace(seed.settings, environment="development")
        )
        access = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == "PFA-GOD-DEMO")
        )
        assert access is not None, "a fixture-nek demo hozzáférést kell létrehoznia"
        assert verify_password(DEMO_PARTNER_CODE, access.access_code_hash)

    def test_reseed_updates_existing_partner_access_hash_to_current_code(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Közvetlen restart/reseed regresszió: az új folyamat új kódot hoz,
        a már létező PartnerFieldAccess hash-e a login oldal által kiírt
        aktuális kódhoz frissül."""
        monkeypatch.setattr(
            seed, "settings", dataclasses.replace(seed.settings, environment="development")
        )
        access = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == "PFA-GOD-DEMO")
        )
        assert access is not None
        assert verify_password(DEMO_PARTNER_CODE, access.access_code_hash)

        # Újraindítás szimulációja: az új folyamat más partner-kódot használ.
        monkeypatch.setattr(seed, "DEMO_PARTNER_CODE", "112233")
        seed_database(db)
        db.flush()

        refreshed = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == "PFA-GOD-DEMO")
        )
        assert refreshed is not None
        # A PBKDF2 hash sózott, ezért közvetlen összehasonlítás helyett
        # verify_password bizonyítja, hogy a tárolt hash az új kódhoz tartozik.
        assert verify_password("112233", refreshed.access_code_hash)
        assert not verify_password("000000", refreshed.access_code_hash)

    def test_production_seed_creates_no_synthetic_partner_access(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Production útvonalon nem jöhet létre gyenge vagy aktív szintetikus
        partneri hozzáférés -- a DEMO_FEATURES_ENABLED flag erőltetése esetén
        sem."""
        for worker in db.scalars(select(PartnerWorker)).all():
            db.delete(worker)
        for access in db.scalars(select(PartnerFieldAccess)).all():
            db.delete(access)
        db.flush()

        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        assert demo_accounts_allowed() is False
        seed_database(db)
        db.flush()

        assert db.scalars(select(PartnerFieldAccess)).all() == []

    def test_disabled_demo_runtime_creates_no_partner_access_even_in_development(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for worker in db.scalars(select(PartnerWorker)).all():
            db.delete(worker)
        for access in db.scalars(select(PartnerFieldAccess)).all():
            db.delete(access)
        db.flush()

        monkeypatch.setattr(
            seed,
            "settings",
            dataclasses.replace(
                seed.settings, environment="development", demo_features_enabled=False
            ),
        )
        assert demo_accounts_allowed() is False
        seed_database(db)
        db.flush()

        assert db.scalars(select(PartnerFieldAccess)).all() == []


class TestProductionDemoAccountGate:
    """Production adatbázisba szintetikus demo fiók nem kerülhet."""

    def test_production_refuses_demo_accounts_even_when_flag_is_forced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forced = _production_settings(demo_features_enabled=True)
        # A flag önmagában production alatt is igazra kényszeríti a demo runtime-ot...
        assert forced.demo_runtime_enabled is True
        # ...a felhasználás pontján lévő kapu viszont fail-closed marad.
        monkeypatch.setattr(seed, "settings", forced)
        assert demo_accounts_allowed() is False

    def test_non_production_keeps_demo_accounts_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            seed, "settings", dataclasses.replace(seed.settings, environment="development")
        )
        assert demo_accounts_allowed() is True

    def test_production_seed_run_creates_no_demo_user(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A worker belépési pontja nem futtat validate()-et, ezért ez a valódi kapu."""
        seeded = db.scalars(select(User).where(User.email.like("%@imperial.local"))).all()
        assert seeded, "a fixture-nek demo fiókokat kell létrehoznia"

        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        seed_database(db)
        db.flush()

        remaining = db.scalars(select(User).where(User.email.like("%@imperial.local"))).all()
        assert remaining, "a meglévő sorok nem tűnnek el, csak inaktiválódnak"
        assert all(not user.active for user in remaining)

    def test_production_seed_run_on_empty_database_adds_no_demo_user(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for user in db.scalars(select(User).where(User.email.like("%@imperial.local"))).all():
            db.delete(user)
        db.flush()

        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        seed_database(db)
        db.flush()

        assert db.scalars(select(User).where(User.email.like("%@imperial.local"))).all() == []
