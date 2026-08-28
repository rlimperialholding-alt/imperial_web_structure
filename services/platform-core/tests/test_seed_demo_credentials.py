"""A szintetikus demo-belépés forrás- és production-kapu regressziója."""

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
    DEMO_PARTNER_ACCESS_ID,
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
from app.services.partner_field import access_is_valid, authenticate_access

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
# Ugyanilyen sentinel a NEM-demo (szintetikus, de nem a demo azonosítójú)
# partneri sorhoz: a tisztítás hatókör-szűkítését bizonyítja.
NON_DEMO_ACCESS_HASH = "non-demo-hash"
NON_DEMO_ACCESS_ID = "PFA-SYNTHETIC-NON-DEMO-01"
NON_DEMO_WORKER_ID = "PWR-SYNTHETIC-NON-DEMO-01"


def _production_settings(**overrides):
    return dataclasses.replace(seed.settings, environment="production", **overrides)


def _synthetic_partner_state(db) -> dict:
    """A szintetikus demo partneri hozzáférés megfigyelhető állapota."""
    access = db.scalar(
        select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == DEMO_PARTNER_ACCESS_ID)
    )
    workers = db.scalars(
        select(PartnerWorker)
        .where(PartnerWorker.access_id == DEMO_PARTNER_ACCESS_ID)
        .order_by(PartnerWorker.worker_id)
    ).all()
    return {
        "access": None if access is None else (access.active, access.access_code_hash),
        "workers": [(worker.worker_id, worker.active) for worker in workers],
    }


class TestSeedSourceHasNoCredentialLiteral:
    """A `Secret Keyword` találat forrásoldali megszűnésének bizonyítéka."""

    def test_no_credential_shaped_literal_in_seed_source(self) -> None:
        assert _CREDENTIAL_LITERAL.findall(SEED_SOURCE) == []

    def test_effective_demo_value_is_not_a_contiguous_source_literal(self) -> None:
        assert DEMO_PASSWORD not in SEED_SOURCE

    def test_demo_value_is_generated_per_process_and_never_blank(self) -> None:
        assert len(DEMO_PASSWORD) == 24
        assert _URLSAFE.fullmatch(DEMO_PASSWORD)
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
        assert f'"{DEMO_PARTNER_CODE}"' not in SEED_SOURCE

    def test_previous_fixed_partner_code_is_absent_from_seed_source(self) -> None:
        assert "654321" not in SEED_SOURCE

    def test_partner_code_is_generated_per_process_and_matches_the_ui_contract(self) -> None:
        assert re.fullmatch(r"[0-9]{6}", DEMO_PARTNER_CODE)
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
        """A belépő oldal nem írhat ki forrásból rekonstruálható fix kódot."""
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
    """A demo-belépés közös, nem követett futásidejű állapota: többfolyamatos
    és újraindítás utáni konzisztencia, a seedelő és a login oldalt renderelő
    folyamat ugyanazt az értéket látja."""

    def test_shared_state_makes_values_stable_across_processes(self, tmp_path: Path) -> None:
        state_path = tmp_path / "demo-credentials-state.json"
        first = demo_runtime_credentials({}, state_path=state_path)
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


def _spawn_seed_process(
    code: str, *args: str, env: dict[str, str]
) -> subprocess.Popen[str]:
    """Egy valódi OS-alfolyamat, amely a tényleges app.seed modult importálja.

    ``sys.argv[1]`` mindig a platform-core gyökér, utána a hívó argumentumai
    következnek; a plaintext szintetikus értékek csak a folyamat stdoutján és
    a tmp_path alatti állapotfájlban jelennek meg.
    """
    platform_core = Path(seed.__file__).resolve().parents[1]
    return subprocess.Popen(
        [sys.executable, "-c", code, str(platform_core), *args],
        cwd=str(platform_core),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _collect_processes(processes: list[subprocess.Popen[str]]) -> list[tuple[str, str]]:
    """A ``(demoLogin, demoPartnerCode)`` párok begyűjtése kilépőkód-ellenőrzéssel."""
    results: list[tuple[str, str]] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=300)
        assert process.returncode == 0, stderr
        lines = stdout.splitlines()
        assert len(lines) == 2, stdout
        results.append((lines[0], lines[1]))
    return results


_STATE_WORKER_CODE = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from app import seed\n"
    "print(seed.DEMO_PASSWORD)\n"
    "print(seed.DEMO_PARTNER_CODE)\n"
)


def _spawn_state_workers(state_path: Path, count: int) -> list[subprocess.Popen[str]]:
    """``count`` valódi OS-folyamat, amely az importtal létrehozza az állapotot."""
    env = {**os.environ, DEMO_CREDENTIALS_STATE_ENV: str(state_path)}
    return [_spawn_seed_process(_STATE_WORKER_CODE, env=env) for _ in range(count)]


_OVERRIDE_WRITER_CODE = (
    "import sys, time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from app import seed\n"
    "state_path = seed.Path(sys.argv[2])\n"
    "lock_path = seed._demo_credentials_lock_path(state_path)\n"
    "if not seed._try_create_demo_state_lock(lock_path):\n"
    "    raise SystemExit(9)\n"
    "print('LOCKED', flush=True)\n"
    "time.sleep(float(sys.argv[3]))\n"
    "converged = seed._resolve_demo_state_under_lock(\n"
    "    state_path, sys.argv[4], '', {}\n"
    ")\n"
    "seed._release_demo_state_lock(lock_path)\n"
    "print(converged[0], flush=True)\n"
    "print(converged[1], flush=True)\n"
)
_READER_CODE = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from app import seed\n"
    "pair = seed.demo_runtime_credentials({}, state_path=seed.Path(sys.argv[2]))\n"
    "print(pair[0], flush=True)\n"
    "print(pair[1], flush=True)\n"
)


class TestDemoCredentialsConcurrentCreation:
    """Valódi többfolyamatos verseny az első állapotlétrehozásra."""

    def test_concurrent_first_creation_converges_and_restarts_stably(self, tmp_path: Path) -> None:
        """Négy egyidejű folyamat, egyetlen konvergens állapot, restart-stabilitás."""
        state_path = tmp_path / "demo-credentials-state.json"
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        results = _collect_processes(_spawn_state_workers(state_path, 4))
        assert len(set(results)) == 1, results
        login, partner = results[0]
        assert len(login) == 24
        assert _URLSAFE.fullmatch(login)
        assert re.fullmatch(r"[0-9]{6}", partner)
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (login, partner)
        assert document["kind"] == "demo-credentials-runtime-state"
        assert not lock_path.exists()
        restart = _collect_processes(_spawn_state_workers(state_path, 1))
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
        first = _collect_processes(_spawn_state_workers(state_path, 1))[0]
        state_path.unlink()
        results = _collect_processes(_spawn_state_workers(state_path, 4))
        assert len(set(results)) == 1, results
        login, partner = results[0]
        assert (login, partner) != first, "az új verseny friss értéket generált"
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (login, partner)

    def test_corrupt_state_self_heals_under_concurrent_creation(self, tmp_path: Path) -> None:
        """Sérült állapot mellett is egyetlen folyamat gyógyít, mindenki konvergál."""
        state_path = tmp_path / "demo-credentials-state.json"
        state_path.write_text("{not valid json", encoding="utf-8")
        results = _collect_processes(_spawn_state_workers(state_path, 3))
        assert len(set(results)) == 1, results
        login, partner = results[0]
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (login, partner)
        assert document["kind"] == "demo-credentials-runtime-state"

    def test_creation_lock_is_exclusive_and_reentrant_after_release(self, tmp_path: Path) -> None:
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
                assert not state_path.exists()
        finally:
            seed._release_demo_state_lock(lock_path)
        resolved = demo_runtime_credentials({}, state_path=state_path)
        assert len(resolved[0]) == 24
        assert re.fullmatch(r"[0-9]{6}", resolved[1])

    def test_unsafe_state_target_fails_closed(self, tmp_path: Path) -> None:
        """Könyvtár vagy szimlink a state/lock útvonalon: fail-closed, nem
        öngyógyítás -- az átirányítás-védelem része is ez a szerződés."""
        state_path = tmp_path / "demo-credentials-state.json"
        state_path.mkdir()
        with pytest.raises(seed.DemoCredentialsStateError):
            demo_runtime_credentials({}, state_path=state_path)
        state_path.rmdir()
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        lock_path.mkdir()
        with pytest.raises(seed.DemoCredentialsStateError):
            demo_runtime_credentials({}, state_path=state_path)
        lock_path.rmdir()
        target = tmp_path / "elsewhere.json"
        try:
            state_path.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable on this host")
        with pytest.raises(seed.DemoCredentialsStateError):
            demo_runtime_credentials({}, state_path=state_path)


class TestDemoCredentialsMixedOverrideConcurrency:
    """Vegyes override/no-override többfolyamatos verseny regressziója."""

    def test_mixed_override_and_no_override_processes_converge(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Override-írás közbeni no-override olvasók: nincs elavult visszatérés."""
        monkeypatch.delenv(DEMO_LOGIN_ENV, raising=False)
        monkeypatch.delenv(DEMO_PARTNER_CODE_ENV, raising=False)
        state_path = tmp_path / "demo-credentials-state.json"
        lock_path = tmp_path / "demo-credentials-state.json.lock"
        pre_login = "pre-" + "override-" + "login"
        pre_partner = "000111"
        override_login = "operator-" + "supplied-" + "value"
        seed._write_demo_credentials_state(state_path, pre_login, pre_partner)

        env = {**os.environ, DEMO_CREDENTIALS_STATE_ENV: str(state_path)}
        env.pop(DEMO_LOGIN_ENV, None)
        env.pop(DEMO_PARTNER_CODE_ENV, None)

        # Az override-író a lockot fogva tartja a kritikus szakaszban, hogy az
        # olvasók az írás KÖZBEN próbálkozzanak -- a régi, elavult állapot
        # éppen elérhető a lemezen, ezért a lock nélküli gyorsút visszaadná.
        writer = _spawn_seed_process(
            _OVERRIDE_WRITER_CODE, str(state_path), "1.5", override_login, env=env
        )
        assert writer.stdout is not None
        first_line = writer.stdout.readline().strip()
        assert first_line == "LOCKED", writer.stderr.read() if writer.stderr else ""

        # A lock fogása közben indított, override nélküli olvasók: a javítás
        # nélkül azonnal az elavult (pre-override) állapotot kapnák; a
        # lock-koordinációval a persistált override-állapothoz konvergálnak.
        readers = [_spawn_seed_process(_READER_CODE, str(state_path), env=env) for _ in range(3)]
        for reader in readers:
            stdout, stderr = reader.communicate(timeout=120)
            assert reader.returncode == 0, stderr
            assert stdout.splitlines() == [override_login, pre_partner], stdout

        writer_stdout, writer_stderr = writer.communicate(timeout=120)
        assert writer.returncode == 0, writer_stderr
        assert writer_stdout.splitlines()[-2:] == [override_login, pre_partner]

        # A persistált állapot pontosan az override-pár, a lock felszabadult:
        document = json.loads(state_path.read_text(encoding="utf-8"))
        assert (document["demoLogin"], document["demoPartnerCode"]) == (
            override_login,
            pre_partner,
        )
        assert not lock_path.exists()

        restart = _spawn_seed_process(_READER_CODE, str(state_path), env=env)
        stdout, stderr = restart.communicate(timeout=120)
        assert restart.returncode == 0, stderr
        assert stdout.splitlines() == [override_login, pre_partner]

        # Disclosure: a plaintext szintetikus értékek sehol a tracked
        # forrásban, és a munkafa sem piszkolódott.
        repo_root = Path(seed.__file__).resolve().parents[3]
        grep = subprocess.run(
            ["git", "grep", "-l", "-e", override_login, "-e", pre_login],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert grep.returncode == 1, grep.stdout
        status_output = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(repo_root),
            text=True,
            encoding="utf-8",
        )
        assert override_login not in status_output
        assert "demo-credentials-state" not in status_output


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

        monkeypatch.setattr(seed, "DEMO_PARTNER_CODE", "112233")
        seed_database(db)
        db.flush()

        refreshed = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == "PFA-GOD-DEMO")
        )
        assert refreshed is not None
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

    def test_demo_disabled_seed_deactivates_pre_existing_synthetic_access(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Task39 review HIGH közvetlen regressziója: nincs bennmaradó
        hozzáférés. A korábbi kód a zárt kapun passzívan visszatért, ezért
        """
        access = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == DEMO_PARTNER_ACCESS_ID)
        )
        assert access is not None, "a fixture-nek aktív demo hozzáférést kell létrehoznia"
        assert access.active is True
        # Egy negyedik munkavállaló, amely NEM a seed három alapsora közül való,
        # de a szintetikus hozzáférés alatt kap felhatalmazást: ennek is le kell
        # zárulnia, különben a tisztítás csak a három ismert azonosítót fedné.
        db.add(
            PartnerWorker(
                worker_id="PWR-GOD-DEMO-EXTRA",
                access_id=DEMO_PARTNER_ACCESS_ID,
                name="Szintetikus Extra Munkás",
                role="Segédmunkás",
                active=True,
            )
        )
        db.flush()
        assert authenticate_access(db, DEMO_PARTNER_CODE) is not None

        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        assert demo_accounts_allowed() is False
        seed_database(db)
        db.flush()

        retired = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == DEMO_PARTNER_ACCESS_ID)
        )
        assert retired is not None
        assert retired.active is False
        assert access_is_valid(retired) is False
        workers = db.scalars(
            select(PartnerWorker).where(PartnerWorker.access_id == DEMO_PARTNER_ACCESS_ID)
        ).all()
        assert len(workers) == 4, "a szintetikus munkavállalói sorok auditálhatóan megmaradnak"
        assert [worker.active for worker in workers] == [False] * 4
        assert authenticate_access(db, DEMO_PARTNER_CODE) is None

    def test_repeated_demo_disabled_cleanup_is_idempotent(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ismételt tisztítás biztonságos: a második futás nem változtat semmit."""
        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        assert demo_accounts_allowed() is False
        seed_database(db)
        db.flush()
        first = _synthetic_partner_state(db)
        assert first["access"] is not None
        assert first["access"][0] is False
        assert first["workers"] and all(not active for _, active in first["workers"])

        seed_database(db)
        db.flush()
        assert _synthetic_partner_state(db) == first

    def test_demo_disabled_cleanup_never_touches_a_non_demo_partner_access(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A tisztítás pontos azonosítóra hat, nem prefixre vagy mintára."""
        db.add(
            PartnerFieldAccess(
                access_id=NON_DEMO_ACCESS_ID,
                company_name="Szintetikus Nem-Demo Partner Kft.",
                project_id="IMP-SYNTHETIC-001",
                work_package_id="WP-SYNTHETIC-001",
                access_code_hash=NON_DEMO_ACCESS_HASH,
                active=True,
                attendance_required=True,
                can_report_changes=True,
            )
        )
        db.add(
            PartnerWorker(
                worker_id=NON_DEMO_WORKER_ID,
                access_id=NON_DEMO_ACCESS_ID,
                name="Szintetikus Nem-Demo Munkás",
                role="Kőműves",
                active=True,
            )
        )
        db.flush()

        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        seed_database(db)
        db.flush()

        untouched = db.scalar(
            select(PartnerFieldAccess).where(PartnerFieldAccess.access_id == NON_DEMO_ACCESS_ID)
        )
        assert untouched is not None
        assert untouched.active is True
        assert untouched.access_code_hash == NON_DEMO_ACCESS_HASH
        untouched_worker = db.scalar(
            select(PartnerWorker).where(PartnerWorker.worker_id == NON_DEMO_WORKER_ID)
        )
        assert untouched_worker is not None
        assert untouched_worker.active is True
        state = _synthetic_partner_state(db)
        assert state["access"] is not None
        assert state["access"][0] is False

    def test_demo_reseed_reactivates_a_previously_retired_synthetic_access(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lezárás visszafordítható: a demo kapun belül újra aktív, friss kóddal."""
        monkeypatch.setattr(seed, "settings", _production_settings(demo_features_enabled=True))
        seed_database(db)
        db.flush()
        retired = _synthetic_partner_state(db)
        assert retired["access"] is not None and retired["access"][0] is False

        monkeypatch.setattr(
            seed, "settings", dataclasses.replace(seed.settings, environment="development")
        )
        monkeypatch.setattr(seed, "DEMO_PARTNER_CODE", "445566")
        assert demo_accounts_allowed() is True
        seed_database(db)
        db.flush()

        restored = _synthetic_partner_state(db)
        assert restored["access"] is not None
        assert restored["access"][0] is True
        assert restored["workers"] and all(active for _, active in restored["workers"])
        assert verify_password("445566", restored["access"][1])
        assert authenticate_access(db, "445566") is not None


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
