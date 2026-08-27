from datetime import UTC, datetime, timedelta
from html import escape

import pytest

from app.autonomous_publishing.adapters import NIMAdminSessionAdapter
from app.autonomous_publishing.registry import Binding, RegistryError
from app.autonomous_publishing.schemas import GateResultIn, PublicationJobIn


class FakeResponse:
    def __init__(self, *, text: str = "", location: str | None = None) -> None:
        self.text = text
        self.headers = {"Location": location} if location else {}


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def request(self, adapter: str, method: str, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"adapter": adapter, "method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def binding() -> Binding:
    return Binding(
        brand_id="bautica",
        domain="bautica.hu",
        cms_route="NIM",
        channel="nim_cms",
        config={
            "enabled": True,
            "base_url": "https://bautica.hu/",
            "mode": "admin_session_live",
            "login_submit_path": "/admin_site/in",
            "create_path": "/admin_article/save_new",
            "read_path": "/admin_article/edit/{external_id}",
            "disable_path": "/admin_article/enable",
            "default_category_id": "2",
        },
        secret={
            "login_url": "https://bautica.hu/admin_site/login",
            "username": "publisher@example.invalid",
            "password": "not-a-real-secret",
        },
    )


def job(*, featured_image_id: str = "") -> PublicationJobIn:
    now = datetime.now(UTC)
    return PublicationJobIn(
        job_id="JOB-NIM-1",
        content_asset_id="ASSET-NIM-1",
        content_version_id="1",
        brand_id="bautica",
        visual_asset_package_id="VISUAL-NIM-1",
        claim_ids=["CLAIM-1"],
        price_snapshot_id="PRICE-1",
        offer_version_id="OFFER-1",
        terms_version_id="TERMS-1",
        gate_results=[
            GateResultIn(
                gate="brand_voice",
                decision="PASS",
                evidence_id="EVIDENCE-1",
                checked_at=now,
                valid_until=now + timedelta(days=1),
            )
        ],
        cta={"label": "Kapcsolat", "url": "https://bautica.hu/kapcsolat"},
        title="Teszt cikk",
        canonical_slug="teszt-cikk",
        body_html="<p>Teszt tartalom.</p>",
        excerpt="Teszt kivonat.",
        content_hash="1" * 64,
        channels=["nim_cms"],
        channel_payloads={
            "nim_cms": {
                "draft_only": False,
                "publish_live": True,
                "featured_image_id": featured_image_id,
                "owner_policy_release_id": "OWNER-AUTO-PUBLISH-2026-08-23",
            }
        },
        cms_route="NIM",
        idempotency_key="2" * 64,
        desired_publish_at=datetime(2026, 8, 27, tzinfo=UTC),
        correlation_id="CORR-NIM-1",
        release_token="r" * 32,
        release_token_hash="3" * 64,
        seo_title="Teszt SEO cím",
        meta_description="Teszt meta leírás.",
        categories=["2"],
    )


def test_admin_session_adapter_publishes_with_image_and_reads_it_back() -> None:
    draft = job(featured_image_id="content/blog/verified-image.png")
    add_form_html = (
        '<input name="params[hu_HU]" value="">'
        '<select name="params[categorie]"><option value="">Nincs</option></select>'
        '<select name="params[user_public]">'
        '<option value="1">Rendszer</option><option value="3">Szerkesztő</option>'
        '</select>'
    )
    readback_html = (
        f'<input name="params[hu_HU]" value="{escape(draft.title)}">'
        f'<input name="params[hu_HU_url]" value="{draft.canonical_slug}">'
        f'<textarea name="params[hu_HU_text]">{escape(draft.body_html)}</textarea>'
        '<input name="params[image]" value="content/blog/verified-image.png">'
        '<select name="params[enable]"><option value="1" selected>Igen</option></select>'
    )
    client = FakeClient(
        [
            FakeResponse(),
            FakeResponse(),
            FakeResponse(text=add_form_html),
            FakeResponse(location="/admin_article/add"),
            FakeResponse(
                text=(
                    '<tr><a href="/admin_article/edit/321">teszt-cikk</a>'
                    '<input name="id" value="321"></tr>'
                )
            ),
            FakeResponse(),
            FakeResponse(text=readback_html),
            FakeResponse(text=f"<h1>{draft.title}</h1>"),
        ]
    )
    adapter = NIMAdminSessionAdapter(binding(), client)

    result = adapter.publish(draft, draft.idempotency_key)

    assert result.external_id == "321"
    assert result.public_url == "https://bautica.hu/blog/teszt-cikk"
    assert result.admin_url == "https://bautica.hu/admin_article/edit/321"
    assert result.readback == {
        "draft_only": False,
        "enabled": True,
        "title_verified": True,
        "slug_verified": True,
        "body_verified": True,
        "public_title_verified": True,
        "featured_image_present": True,
        "image_required_followup": False,
    }
    create_call = client.calls[3]
    assert create_call["data"]["params[enable]"] == "0"
    assert create_call["data"]["params[image]"] == "content/blog/verified-image.png"
    assert create_call["data"]["params[categorie]"] == "2"
    assert create_call["data"]["params[user_public]"] == "3"
    assert create_call["data"]["params[language]"] == ""
    assert create_call["data"]["params[hu_HU_robots_type]"] == ""
    assert create_call["data"]["params[hu_HU_robots]"] == "INDEX, FOLLOW"
    assert create_call["data"]["params[date_public]"] == "2026-08-27"
    assert "params[categories][]" not in create_call["data"]
    assert "params[related][]" not in create_call["data"]
    assert "params[labels][]" not in create_call["data"]
    assert "params[images][]" not in create_call["data"]
    enable_call = client.calls[5]
    assert enable_call["url"] == "https://bautica.hu/admin_article/enable"
    assert enable_call["data"]["id"] == "321"
    assert enable_call["data"]["value"] == "1"


def test_admin_session_adapter_blocks_image_less_live_publication() -> None:
    adapter = NIMAdminSessionAdapter(binding(), FakeClient([]))
    draft = job(featured_image_id="content/blog/verified-image.png")
    draft.channel_payloads["nim_cms"]["featured_image_id"] = ""
    with pytest.raises(RegistryError, match="requires a featured image"):
        adapter.preflight(draft)
