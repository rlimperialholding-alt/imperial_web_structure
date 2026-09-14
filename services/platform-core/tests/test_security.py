import dataclasses
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import main as main_module
from app import seed as seed_module
from app.config import Settings
from app.seed import DEMO_PARTNER_CODE, DEMO_PASSWORD, demo_accounts_allowed


def test_production_validation_blocks_unsafe_defaults(monkeypatch):
    # The dataclass can be constructed explicitly for a deterministic validation test.
    unsafe = Settings(
        environment="production",
        database_url="sqlite:///x.db",
        session_secret="short",
        api_token="",
    )
    errors = unsafe.validate()
    assert len(errors) == 4


def test_production_disables_demo_runtime_by_default():
    production = Settings(environment="production")

    assert production.demo_runtime_enabled is False


DEMO_FEATURES_ERROR = "Production environment must not enable DEMO_FEATURES_ENABLED."
DEMO_OVERRIDE_ERROR = "Production environment must not enable DEMO_RUNTIME_ENABLED."


def _production_with_demo(**demo_flags):
    return Settings(
        environment="production",
        database_url="postgresql+psycopg://platform@postgres/platform",
        session_secret="s" * 32,
        api_token="api-token",
        require_https=True,
        **demo_flags,
    )


def _demo_errors(errors):
    return [error for error in errors if "DEMO_" in error]


def test_production_rejects_explicit_demo_runtime():
    production = _production_with_demo(demo_features_enabled=True)

    demo_errors = _demo_errors(production.validate())
    # Pontos, stabil hibaszemantika: a features flag saját üzenete, kizárólag
    # az (az override flag említése nélkül).
    assert demo_errors == [DEMO_FEATURES_ERROR]


def test_production_rejects_explicit_demo_runtime_override():
    production = _production_with_demo(demo_runtime_enabled_override=True)

    assert production.demo_runtime_enabled is True
    demo_errors = _demo_errors(production.validate())
    assert demo_errors == [DEMO_OVERRIDE_ERROR]


def test_production_rejects_both_demo_flags_with_distinct_messages():
    production = _production_with_demo(
        demo_runtime_enabled_override=True,
        demo_features_enabled=True,
    )

    demo_errors = _demo_errors(production.validate())
    assert DEMO_OVERRIDE_ERROR in demo_errors
    assert DEMO_FEATURES_ERROR in demo_errors


def test_production_override_false_does_not_mask_features_activation():
    # Az override=False + features=True kombináció production alatt akkor is
    # tiltott, ha a származtatott demo_runtime_enabled értéke hamis: egyetlen
    # explicit demo-aktiválás sem maradhat a precedence árnyékában.
    production = _production_with_demo(
        demo_runtime_enabled_override=False,
        demo_features_enabled=True,
    )

    assert production.demo_runtime_enabled is False
    demo_errors = _demo_errors(production.validate())
    assert demo_errors == [DEMO_FEATURES_ERROR]


def test_production_explicit_demo_disable_and_defaults_are_accepted():
    disabled = _production_with_demo(demo_runtime_enabled_override=False)
    assert disabled.demo_runtime_enabled is False
    assert _demo_errors(disabled.validate()) == []

    defaults = _production_with_demo()
    assert defaults.demo_runtime_enabled is False
    assert _demo_errors(defaults.validate()) == []


def test_non_production_allows_demo_activations():
    for environment in ("development", "staging"):
        for demo_flags in (
            {"demo_features_enabled": True},
            {"demo_runtime_enabled_override": True},
        ):
            allowed = Settings(environment=environment, **demo_flags)
            assert allowed.demo_runtime_enabled is True
            assert _demo_errors(allowed.validate()) == []
        masked = Settings(
            environment=environment,
            demo_runtime_enabled_override=False,
            demo_features_enabled=True,
        )
        assert masked.demo_runtime_enabled is False
        assert _demo_errors(masked.validate()) == []


def test_live_ai_routing_requires_provider_key_and_budget():
    unsafe = Settings(
        ai_external_calls_enabled=True,
        ai_monthly_budget_usd=0,
        ai_provider_api_key_file="",
    )
    errors = unsafe.validate()
    assert any("AI_MONTHLY_BUDGET_USD" in error for error in errors)
    assert any("AI_PROVIDER_API_KEY_FILE" in error for error in errors)


def test_external_publication_requires_separate_expert_review_secret():
    unsafe = Settings(
        environment="production",
        database_url="postgresql+psycopg://platform@postgres/platform",
        session_secret="s" * 32,
        api_token="api-token",
        internal_job_token="job-token",
        content_external_publishing_enabled=True,
        content_expert_review_secret="",
        content_marketing_review_secret="",
        content_copywriter_review_secret="",
        content_visual_review_secret="",
        content_campaign_package_secret="",
        imperial_release_hmac_key="",
    )

    errors = unsafe.validate()

    assert any("CONTENT_EXPERT_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_MARKETING_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_COPYWRITER_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_VISUAL_REVIEW_SECRET" in error for error in errors)
    assert any("CONTENT_CAMPAIGN_PACKAGE_SECRET" in error for error in errors)
    assert any("IMPERIAL_RELEASE_HMAC_KEY" in error for error in errors)


def test_external_publication_rejects_shared_gate_secrets():
    shared = "x" * 32
    unsafe = Settings(
        environment="production",
        database_url="postgresql+psycopg://platform@postgres/platform",
        session_secret="s" * 32,
        api_token="api-token",
        internal_job_token="job-token",
        content_external_publishing_enabled=True,
        content_expert_review_secret=shared,
        content_marketing_review_secret=shared,
        content_copywriter_review_secret=shared,
        content_visual_review_secret=shared,
        content_campaign_package_secret=shared,
        imperial_release_hmac_key=shared,
    )

    assert any("különálló secretet" in error for error in unsafe.validate())


def test_house_design_order_intake_requires_adapter_kill_switch():
    unsafe = Settings(
        house_design_order_intake_enabled=True,
        house_designer_adapters_enabled=False,
    )

    assert any(
        "HOUSE_DESIGN_ORDER_INTAKE_ENABLED requires HOUSE_DESIGNER_ADAPTERS_ENABLED" in error
        for error in unsafe.validate()
    )


def test_house_designer_site_encryption_requires_a_distinct_key():
    shared = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    unsafe = Settings(
        market_evidence_kek=shared,
        house_designer_site_kek=shared,
    )

    assert any(
        "House Designer és Market titkosítási kulcsa nem lehet azonos" in error
        for error in unsafe.validate()
    )


def test_crm_read_connection_requires_a_paired_long_token():
    missing = Settings(crm_read_base_url="https://crm.example.invalid", crm_read_token="")
    short = Settings(
        crm_read_base_url="https://crm.example.invalid",
        crm_read_token="too-short",
    )

    assert any("CRM_READ_BASE_URL" in error for error in missing.validate())
    assert any("CRM_READ_TOKEN legalább 32" in error for error in short.validate())


def test_crm_read_write_and_sites_credentials_must_be_separate():
    shared = "x" * 32
    unsafe = Settings(
        crm_read_base_url="https://crm.example.invalid",
        crm_read_token=shared,
        crm_write_base_url="https://crm.example.invalid",
        crm_write_token=shared,
        crm_sites_bypass_token=shared,
    )

    errors = unsafe.validate()
    assert any("olvasási és írási tokenje nem lehet azonos" in error for error in errors)
    assert any("Sites hozzáférési tokenje" in error for error in errors)


def test_anonymous_ui_redirects(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login?return_to=/"


def test_session_authenticated_writes_require_same_origin(client):
    login = client.post(
        "/login",
        data={"email": "platform-admin@imperial.local", "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert login.status_code == 303

    foreign = client.post(
        "/logout",
        headers={"Origin": "https://attacker.example"},
        follow_redirects=False,
    )
    assert foreign.status_code == 403
    assert "azonos eredetű" in foreign.text

    missing = client.post("/logout", headers={"Origin": ""}, follow_redirects=False)
    assert missing.status_code == 403

    same_origin = client.post(
        "/logout",
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert same_origin.status_code == 303


class TestDemoTemplateCredentialsGate:
    """A login oldalak demo-hitelesítőit ugyanaz a kapu dönti el, mint a seed.

    A Task40 review MEDIUM regressziója: a templátum-globals csak a
    ``settings.is_production``-t nézte, ezért non-production, kikapcsolt demo
    runtime mellett is kiírta a demo hitelesítőket, miközben a seed ilyenkor
    sem demo fiókot, sem szintetikus partneri hozzáférést nem hoz létre. A
    kikapcsolt esetet a ``demo_runtime_enabled`` explicit kapcsolója
    (``DEMO_RUNTIME_ENABLED``) állítja be, nem a megkülönböztetett
    ``demo_features_enabled`` feature-flag: az acceptance eset közvetlenül a
    runtime-értéket rögzíti.
    """

    def test_demo_disabled_non_production_exposes_no_template_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            seed_module,
            "settings",
            dataclasses.replace(
                seed_module.settings,
                environment="staging",
                demo_runtime_enabled_override=False,
            ),
        )
        assert seed_module.settings.demo_runtime_enabled is False
        assert demo_accounts_allowed() is False
        assert main_module._demo_template_credentials() == (None, None)

    def test_demo_enabled_non_production_keeps_template_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            seed_module,
            "settings",
            dataclasses.replace(
                seed_module.settings,
                environment="staging",
                demo_runtime_enabled_override=True,
            ),
        )
        assert seed_module.settings.demo_runtime_enabled is True
        assert main_module._demo_template_credentials() == (DEMO_PASSWORD, DEMO_PARTNER_CODE)

    def test_production_never_exposes_template_credentials_even_with_forced_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            seed_module,
            "settings",
            dataclasses.replace(
                seed_module.settings,
                environment="production",
                demo_runtime_enabled_override=True,
            ),
        )
        assert seed_module.settings.demo_runtime_enabled is True
        assert demo_accounts_allowed() is False
        assert main_module._demo_template_credentials() == (None, None)

    def test_template_globals_are_wired_through_the_shared_gate(self) -> None:
        expected_password, expected_code = main_module._demo_template_credentials()
        assert main_module.templates.env.globals["demo_password"] == expected_password
        assert main_module.templates.env.globals["partner_demo_code"] == expected_code

    def test_demo_disabled_non_production_hides_credentials_end_to_end(
        self, tmp_path: Path
    ) -> None:
        """Friss folyamat, staging + DEMO_RUNTIME_ENABLED=false: a valódi
        import-időben rögzített globals és a renderelt login oldalak sem demo
        jelszót, sem partneri demókódot nem mutatnak."""
        platform_core = Path(seed_module.__file__).resolve().parents[1]
        code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from app import main as app_main\n"
            "from app import seed\n"
            "from fastapi.testclient import TestClient\n"
            "assert not seed.settings.is_production\n"
            "assert seed.settings.demo_runtime_enabled is False\n"
            "assert seed.demo_accounts_allowed() is False\n"
            "print(app_main.templates.env.globals['demo_password'])\n"
            "print(app_main.templates.env.globals['partner_demo_code'])\n"
            "client = TestClient(app_main.app)\n"
            "login_page = client.get('/login').text\n"
            "partner_page = client.get('/partner-field/login').text\n"
            "print(seed.DEMO_PASSWORD in login_page or seed.DEMO_PASSWORD in partner_page)\n"
            "print(seed.DEMO_PARTNER_CODE in login_page or seed.DEMO_PARTNER_CODE in partner_page)\n"
        )
        env = {
            **os.environ,
            "ENVIRONMENT": "staging",
            "DEMO_RUNTIME_ENABLED": "false",
            "DEMO_CREDENTIALS_STATE_PATH": str(tmp_path / "demo-credentials-state.json"),
        }
        completed = subprocess.run(
            [sys.executable, "-c", code, str(platform_core)],
            cwd=str(platform_core),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.splitlines() == ["None", "None", "False", "False"]
