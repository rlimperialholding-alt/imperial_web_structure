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
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app import seed
from app.models import User
from app.seed import (
    DEMO_LOGIN_ENV,
    DEMO_PARTNER_CODE,
    DEMO_PARTNER_CODE_ENV,
    DEMO_PASSWORD,
    DEMO_PASSWORD_HASH,
    demo_accounts_allowed,
    demo_login_value,
    demo_partner_code,
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
