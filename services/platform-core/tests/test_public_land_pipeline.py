from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.growth_ops import catalog, public_land, service
from app.growth_ops import registry as growth_registry
from app.growth_ops.email import EmailDeliveryError, EmailReceipt
from app.growth_ops.models import (
    GrowthLandCanarySlot,
    GrowthLandCanaryState,
    GrowthPublicLandListingCursor,
    GrowthSignal,
    GrowthSignalSourceEvidence,
    OutreachMessage,
    SourceCatalogRevision,
    SourceCoverageAttempt,
    SourceCoverageRoute,
)
from app.growth_ops.registry import BrandBinding, GrowthRegistryError
from app.land_acquisition.service import (
    ensure_public_html_land_routes,
    managed_public_land_route_set_sha256,
    public_land_route_readiness,
)
from app.models import MailSendingDomain


class _Registry:
    sources = {
        "construction_public_land_html": {
            "enabled": True,
            "motor": "construction",
            "bucket": "property_development",
            "kind": "public_land_listing_html",
            "fetch_mode": "ingest_only",
            "route_set_sha256": managed_public_land_route_set_sha256(),
        },
        "construction_scheduled_test": {
            "enabled": True,
            "motor": "construction",
            "bucket": "etdr",
            "kind": "json",
            "fetch_mode": "scheduled",
        },
    }

    def validate_signal_source(
        self, *, source_id: str, motor_key: str, source_bucket: str, **_: object
    ):
        assert (source_id, motor_key, source_bucket) == (
            "construction_public_land_html",
            "construction",
            "property_development",
        )

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        assert signal_type == "residential_building_plot"
        assert requested is None
        return "imperial"

    def brand_binding(self, brand_id: str) -> BrandBinding:
        assert brand_id == "imperial"
        return BrandBinding(
            brand_id="imperial",
            sender_email="info@imperialholding.test",
            domain_key="imperial-test",
            secret={"host": "smtp.test", "port": 465, "username": "u", "password": "p"},
            config={
                "brand_name": "Imperial Holding",
                "recipient_cooldown_days": 30,
                "max_daily_messages": 100,
            },
        )


@pytest.fixture
def land_runtime(db, monkeypatch, tmp_path):
    registry = _Registry()
    canonical_path = (
        Path(__file__).resolve().parents[3]
        / "config"
        / "outbound"
        / "canonical_first_contact_templates_hu_v1.json"
    )
    monkeypatch.setenv("CANONICAL_FIRST_CONTACT_REGISTRY_FILE", str(canonical_path))
    monkeypatch.setattr(service.GrowthRegistry, "load", classmethod(lambda cls: registry))
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda *_args: True)
    monkeypatch.setattr(
        service,
        "_outreach_transport_capacity_reserved",
        lambda _db, _row, *_args: True,
    )
    monkeypatch.setattr(
        service,
        "settings",
        lambda: SimpleNamespace(
            base_url="https://intelligence.test.example",
            worker_id="growth-test-worker",
            lease_seconds=300,
            poll_seconds=30,
            enabled=True,
            timezone="Europe/Budapest",
            outreach_max_per_hour=5,
            outreach_max_per_day=50,
            land_outreach_production_canary_max_total=3,
            land_outreach_production_canary_local_date="2026-08-31",
            runtime_kill_switch_file=str(tmp_path / "runtime-growth-kill-switch"),
        ),
    )
    db.add(
        MailSendingDomain(
            domain_key="imperial-test",
            domain_name="imperialholding.test",
            from_email="info@imperialholding.test",
            provider="smtp",
            spf_status="pass",
            dkim_status="pass",
            dmarc_status="pass",
            active=True,
        )
    )
    db.add(
        GrowthLandCanaryState(
            id=1,
            scope_local_date=date(2026, 8, 31),
            max_total=3,
            status="released",
            released_by="test-release",
            released_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    for slot_number in (1, 2, 3):
        db.add(
            GrowthLandCanarySlot(
                scope_local_date=date(2026, 8, 31),
                slot_number=slot_number,
                status="available",
                updated_at=datetime.now(UTC),
            )
        )
    ensure_public_html_land_routes(db, dry_run=False)
    db.commit()
    return registry


def _claim_for_dispatch(db, outreach: OutreachMessage | None = None) -> OutreachMessage:
    row = outreach or db.scalar(select(OutreachMessage))
    assert row is not None
    now = datetime.now(UTC)
    row.status = "claimed"
    row.claimed_by = "growth-test-worker"
    row.claimed_at = now
    row.lease_expires_at = now.replace(microsecond=0) + timedelta(minutes=5)
    row.attempt_count = max(1, row.attempt_count)
    db.commit()
    return row


def _route() -> SourceCoverageRoute:
    return SourceCoverageRoute(
        route_key="LAND-PUBLIC-TEST",
        route_id="LAND-PUBLIC-TEST",
        catalog_sha256="a" * 64,
        motor="Imperial Bautica Prefab",
        category="residential_building_plot",
        route_url="https://ingatlan.com/elado+telek",
        source_row_sha256="b" * 64,
        source_record_json="{}",
    )


def _attempt() -> SourceCoverageAttempt:
    now = datetime.now(UTC)
    return SourceCoverageAttempt(
        attempt_id="SCA-LAND-PUBLIC-TEST",
        route_key="LAND-PUBLIC-TEST",
        catalog_sha256="a" * 64,
        run_id="BUILDING-20260830-V216",
        status="succeeded",
        started_at=now,
        completed_at=now,
    )


def _owner_html(
    *,
    extra: str = "",
    role: str = "Tulajdonos",
    name: str = "Kovács Péter",
    email: str = "kovacs.peter@example.test",
    location: str = "Sülysáp",
    plot_size_sqm: int = 605,
) -> str:
    return f"""
    <html><body>
      <h1>Eladó építési telek</h1>
      <section>
        <dl>
          <dt>{role}</dt><dd>{name}</dd>
          <dt>Település</dt><dd>{location}</dd>
          <dt>Telek mérete</dt><dd>{plot_size_sqm} m²</dd>
          <dt>E-mail</dt>
          <dd><a href="mailto:{email}">E-mail</a></dd>
        </dl>
      </section>
      {extra}
    </body></html>
    """


def _agent_html(*, organization: str = "Független Ingatlanhálózat") -> str:
    return f"""
    <html><body>
      <h1>Eladó építési telek</h1>
      <section>
        <dl>
          <dt>Értékesítő</dt><dd>Nagy Anna</dd>
          <dt>Hálózat</dt><dd>{organization}</dd>
          <dt>Iroda</dt><dd>Pesti Belvárosi Iroda</dd>
          <dt>Település</dt><dd>Érd</dd>
          <dt>Telek területe</dt><dd>800 m2</dd>
          <dt>E-mail</dt>
          <dd><a href="mailto:nagy.anna@example.test">E-mail</a></dd>
        </dl>
      </section>
    </body></html>
    """


def _page(url: str, html: str) -> dict[str, str]:
    return {
        "url": url,
        "html": html,
        "response_sha256": hashlib.sha256(html.encode()).hexdigest(),
    }


def _set_canary_pending(db) -> None:
    state = db.get(GrowthLandCanaryState, 1)
    assert state is not None
    state.status = "pending"
    state.released_by = None
    state.released_at = None
    for slot in db.scalars(select(GrowthLandCanarySlot)):
        slot.status = "available"
        slot.outreach_id = None
        slot.claimed_at = None
        slot.sent_at = None
        slot.provider_message_id = None
    db.commit()


def _dh_html(*, duplicate_payload: bool = False, email: str = "agent@example.test") -> str:
    payload = {
        "status": "success",
        "result": {
            "referenceNumber": "AB123456",
            "alias": "synthetic-building-plot",
            "propertyTypeName": "Telek",
            "subType": "Építési telek",
            "address": "2030 Érd, Minta utca",
            "area": "900.0",
            "description": "Szintetikus építési telek leírás.",
            "agent": {
                "name": "Minta Anna",
                "email": email,
                "career": "Értékesítő",
                "office": "Duna House Minta Iroda",
            },
        },
    }
    assignment = (
        "pageCache['aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'] = "
        + json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)
        + ";"
    )
    scripts = f"<script>{assignment}</script>"
    if duplicate_payload:
        scripts += f"<script>{assignment}</script>"
    return f"""
    <html><head>
      <meta property="og:site_name" content="Duna House">
      {scripts}
    </head><body>
      <h1>Építési telek</h1>
      <p>Duna House</p><p>AB123456</p><p>Érd</p><p>900 m²</p>
      <section>
        <div itemprop="name">Minta Anna</div>
        <div itemprop="description">Értékesítő</div>
        <meta itemprop="email" content="{email}">
        <div>Duna House Minta Iroda</div>
      </section>
    </body></html>
    """


def _ingatlannet_html(*, owner_email: str = "owner@example.test") -> str:
    url = "https://www.ingatlannet.hu/elado-telek-erd/123456"
    payload = {
        "isFallback": False,
        "query": {"id": "123456"},
        "props": {
            "pageProps": {
                "canonical": url,
                "data": {
                    "data": {
                        "id": 123456,
                        "url": "/elado-telek-erd/123456",
                        "status": 1,
                        "estateStatus": 1,
                        "deletedAt": None,
                        "advertiserId": 77,
                        "address": "Érd",
                        "plotSize": 850,
                        "areaSize": "850.0",
                        "description": {"aboutTheProperty": "Szintetikus építési telek leírás."},
                    },
                    "ownerData": {
                        "id": 77,
                        "name": "Teszt Elek",
                        "email": owner_email,
                        "type": "Ingatlanreferens",
                    },
                    "officeData": {"name": "Minta Ingatlaniroda"},
                },
            }
        },
    }
    next_data = json.dumps(payload, ensure_ascii=False)
    return f"""
    <html><body>
      <script id="__NEXT_DATA__" type="application/json">{next_data}</script>
      <h1>Eladó építési telek</h1>
      <p>Teszt Elek</p><p>Ingatlanreferens</p>
      <p>Minta Ingatlaniroda</p><p>Érd</p><p>850 m²</p>
    </body></html>
    """


def test_exact_owner_listing_queues_once_and_persists_field_evidence(db, land_runtime):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500001", html)
    route = _route()
    attempt = _attempt()

    first = public_land.process_public_land_listings(
        db, route=route, attempt=attempt, listing_pages=[page]
    )
    second = public_land.process_public_land_listings(
        db, route=route, attempt=attempt, listing_pages=[page]
    )

    assert first["queued"] == 1 and first["qualified"] == 1
    assert second["queued"] == 1 and second["idempotent"] == 1
    assert db.scalar(select(func.count()).select_from(GrowthSignal)) == 1
    assert db.scalar(select(func.count()).select_from(OutreachMessage)) == 1
    evidence = list(db.scalars(select(GrowthSignalSourceEvidence)))
    assert {row.field_name for row in evidence} == {
        "listing_permalink",
        "recipient_name",
        "recipient_email",
        "recipient_role",
        "property_type",
        "location",
        "plot_size_sqm",
    }
    assert {row.snapshot_sha256 for row in evidence} == {page["response_sha256"]}
    assert all(row.fetched_at and row.source_snippet and row.snippet_sha256 for row in evidence)
    assert all(
        hashlib.sha256(row.source_snippet.encode()).hexdigest() == row.snippet_sha256
        for row in evidence
    )


def test_land_initial_messages_have_isolated_unsubscribe_tokens(db, land_runtime):
    pages = [
        _page(
            "https://ingatlan.com/35500901",
            _owner_html(),
        ),
        _page(
            "https://ingatlan.com/35500902",
            _owner_html(
                name="Szabó Júlia",
                email="szabo.julia@example.test",
                location="Gödöllő",
                plot_size_sqm=720,
            ),
        ),
    ]
    result = public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=pages,
    )

    assert result["queued"] == 2
    messages = list(db.scalars(select(OutreachMessage).order_by(OutreachMessage.id)))
    assert len(messages) == 2
    unsubscribe_urls = [
        json.loads(row.receipt_json)["canonical_template"]["render_input"]["unsubscribe_url"]
        for row in messages
    ]
    unsubscribe_tokens = [url.rsplit("/", 1)[-1] for url in unsubscribe_urls]
    assert len(set(unsubscribe_urls)) == 2
    assert len({row.unsubscribe_token_hash for row in messages}) == 2
    assert {hashlib.sha256(token.encode()).hexdigest() for token in unsubscribe_tokens} == {
        row.unsubscribe_token_hash for row in messages
    }

    service.unsubscribe(db, unsubscribe_tokens[0])
    db.refresh(messages[0])
    db.refresh(messages[1])
    assert messages[0].status == "unsubscribed"
    assert messages[1].status == "queued"

    service.unsubscribe(db, unsubscribe_tokens[1])
    db.refresh(messages[0])
    db.refresh(messages[1])
    assert messages[0].status == "unsubscribed"
    assert messages[1].status == "unsubscribed"


def test_sent_land_message_never_schedules_a_followup(db, land_runtime):
    public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page("https://ingatlan.com/35500903", _owner_html())],
    )
    outreach = db.scalar(select(OutreachMessage))
    outreach.status = "sent"
    outreach.sent_at = datetime(2026, 8, 1, tzinfo=UTC)
    db.commit()

    assert service.schedule_followups(db) == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(OutreachMessage.sequence_step > 0)
        )
        == 0
    )
    assert db.scalar(select(func.count()).select_from(OutreachMessage)) == 1


@pytest.mark.parametrize("tamper_target", ["listing_url", "evidence_manifest"])
def test_listing_agent_url_and_manifest_tamper_invalidate_release_before_provider(
    db, land_runtime, monkeypatch, tamper_target
):
    listing_url = "https://ingatlan.com/35500904"
    result = public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page(listing_url, _agent_html())],
    )

    assert result["queued"] == 1
    signal = db.scalar(select(GrowthSignal))
    outreach = db.scalar(select(OutreachMessage))
    assert signal.recipient_role == "listing_agent"
    metadata = json.loads(outreach.receipt_json)["canonical_template"]
    assert metadata["render_input"]["listing_url"] == listing_url
    assert signal.public_contact_url == listing_url
    assert signal.evidence_url == listing_url
    assert metadata["source_evidence_manifest_sha256"]
    assert service._release_matches(outreach) is True

    if tamper_target == "listing_url":
        metadata["render_input"]["listing_url"] = "https://ingatlan.com/35500904-tampered"
    else:
        metadata["source_evidence_manifest_sha256"] = "f" * 64
    outreach.receipt_json = json.dumps(
        {"canonical_template": metadata},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    db.commit()
    provider_calls = 0

    def fail_if_called(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not run after canonical metadata tamper")

    monkeypatch.setattr(service.SMTPEmailAdapter, "send", fail_if_called)

    assert service._release_matches(outreach) is False
    dispatched = service.dispatch_outreach(db, outreach)
    assert dispatched.status != "sent"
    assert provider_calls == 0
    assert service._release_matches(dispatched) is False


def test_dh_double_json_adapter_requires_unique_identity_bound_payload():
    url = "https://www.dh.hu/ingatlan/AB123456/synthetic-building-plot"
    html = _dh_html()
    decision = public_land.listing_signal_decision(
        route=SourceCoverageRoute(
            route_key="LAND-PUBLIC-HTML:dh",
            route_id="LAND-PUBLIC-DH",
            catalog_sha256="a" * 64,
            motor="construction",
            route_url="https://dh.hu/elado-ingatlan/telek",
            source_row_sha256="b" * 64,
            source_record_json="{}",
        ),
        attempt=_attempt(),
        listing_url=url,
        html=html,
        response_sha256=hashlib.sha256(html.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )

    assert decision.reasons == ()
    assert decision.signal is not None
    assert decision.signal.recipient_email == "agent@example.test"
    assert decision.signal.recipient_organization_name == "Duna House"
    assert decision.signal.recipient_office_name == "Duna House Minta Iroda"
    assert decision.evidence_fields["property_type"] == "Építési telek"
    assert "$.result.agent.email" in next(
        record["source_snippet"]
        for record in decision.evidence_records
        if record["field_name"] == "recipient_email"
    )

    duplicate = public_land.listing_signal_decision(
        route=SourceCoverageRoute(
            route_key="LAND-PUBLIC-HTML:dh",
            route_id="LAND-PUBLIC-DH",
            catalog_sha256="a" * 64,
            motor="construction",
            route_url="https://dh.hu/elado-ingatlan/telek",
            source_row_sha256="b" * 64,
            source_record_json="{}",
        ),
        attempt=_attempt(),
        listing_url=url,
        html=_dh_html(duplicate_payload=True),
        response_sha256="c" * 64,
        source_id="construction_public_land_html",
    )
    assert duplicate.signal is None
    assert "dh_page_cache_not_unique" in duplicate.reasons


def test_ingatlannet_next_data_adapter_binds_owner_and_rendered_listing():
    url = "https://www.ingatlannet.hu/elado-telek-erd/123456"
    html = _ingatlannet_html()
    route = SourceCoverageRoute(
        route_key="LAND-PUBLIC-HTML:ingatlannet",
        route_id="LAND-PUBLIC-INGATLANNET",
        catalog_sha256="a" * 64,
        motor="construction",
        route_url="https://ingatlannet.hu/elado-telek",
        source_row_sha256="b" * 64,
        source_record_json="{}",
    )
    decision = public_land.listing_signal_decision(
        route=route,
        attempt=_attempt(),
        listing_url=url,
        html=html,
        response_sha256=hashlib.sha256(html.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )

    assert decision.reasons == ()
    assert decision.signal is not None
    assert decision.signal.location == "Érd"
    assert decision.signal.plot_size_sqm == 850
    assert decision.signal.recipient_email == "owner@example.test"
    assert decision.signal.recipient_organization_name == "Minta Ingatlaniroda"

    mismatched = html.replace('"advertiserId": 77', '"advertiserId": 78')
    rejected = public_land.listing_signal_decision(
        route=route,
        attempt=_attempt(),
        listing_url=url,
        html=mismatched,
        response_sha256=hashlib.sha256(mismatched.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert rejected.signal is None
    assert "ingatlannet_owner_binding_mismatch" in rejected.reasons


@pytest.mark.parametrize(
    ("html", "reason"),
    [
        (
            _owner_html().replace('<a href="mailto:kovacs.peter@example.test">E-mail</a>', ""),
            "recipient_email_missing",
        ),
        (_owner_html(role="Kapcsolattartó"), "recipient_role_missing"),
        (_owner_html(extra="<p>Tulajdonos: Másik Ember</p>"), "recipient_name_ambiguous"),
        (_owner_html(extra="<p>Hirdető típusa: Ingatlanközvetítő</p>"), "recipient_role_ambiguous"),
    ],
)
def test_missing_or_ambiguous_listing_fields_fail_closed(html, reason):
    decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500002",
        html=html,
        response_sha256=hashlib.sha256(html.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )

    assert decision.signal is None
    assert reason in decision.reasons


def test_contact_binding_accepts_visible_labeled_email_but_rejects_footer_mailto():
    visible = _owner_html().replace(
        '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
        "<p>E-mail: kovacs.peter@example.test</p>",
    )
    accepted = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://www.ingatlan.com/35500100",
        html=visible,
        response_sha256=hashlib.sha256(visible.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert accepted.signal is not None
    assert accepted.signal.recipient_email == "kovacs.peter@example.test"

    footer_only = (
        _owner_html()
        .replace(
            '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
            "",
        )
        .replace(
            "</body>",
            '<footer><a href="mailto:support@example.test">Support</a></footer></body>',
        )
    )
    rejected = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500101",
        html=footer_only,
        response_sha256=hashlib.sha256(footer_only.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert rejected.signal is None
    assert "recipient_email_missing" in rejected.reasons


@pytest.mark.parametrize(
    "layout",
    [
        "footer",
        "nested_sibling",
        "direct_section_sibling",
        "direct_parent_nested_email",
        "agent_affiliation_sibling",
    ],
)
def test_broad_ancestor_never_cross_binds_recipient_contact_evidence(db, land_runtime, layout):
    if layout == "footer":
        listing = _owner_html().replace(
            '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
            "",
        )
        html = listing.replace(
            "<html><body>",
            '<html><body><div id="root">',
        ).replace(
            "</body>",
            (
                '<footer><p>E-mail</p><a href="mailto:support@example.test">'
                "E-mail</a></footer></div></body>"
            ),
        )
    elif layout == "nested_sibling":
        listing = _owner_html().replace(
            '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
            "",
        )
        html = listing.replace(
            "<html><body>",
            '<html><body><div id="root">',
        ).replace(
            "</body>",
            (
                '<div class="support"><p>E-mail</p>'
                '<a href="mailto:support@example.test">E-mail</a>'
                "</div></div></body>"
            ),
        )
    elif layout == "direct_section_sibling":
        listing = _owner_html().replace(
            '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
            "",
        )
        html = listing.replace(
            "</section>",
            (
                '<p class="portal-support-label">E-mail</p>'
                '<a class="portal-support" href="mailto:support@example.test">'
                "E-mail</a></section>"
            ),
        )
    elif layout == "direct_parent_nested_email":
        html = """
        <html><body>
          <h1>Eladó építési telek</h1>
          <section>
            <p>Tulajdonos: Kovács Péter</p>
            <p>Település: Sülysáp</p>
            <p>Telek mérete: 605 m²</p>
            <div class="portal-support">
              <p>E-mail</p>
              <a href="mailto:support@example.test">E-mail</a>
            </div>
          </section>
        </body></html>
        """
    else:
        html = """
        <html><body>
          <h1>Eladó építési telek</h1>
          <div id="root">
            <section>
              <dl>
                <dt>Értékesítő</dt><dd>Nagy Anna</dd>
                <dt>Település</dt><dd>Érd</dd>
                <dt>Telek területe</dt><dd>800 m2</dd>
              </dl>
              <p>E-mail</p>
              <a href="mailto:nagy.anna@example.test">E-mail</a>
            </section>
            <div class="unrelated-affiliation">
              <dl>
                <dt>Hálózat</dt><dd>Független Ingatlanhálózat</dd>
                <dt>Iroda</dt><dd>Pesti Belvárosi Iroda</dd>
              </dl>
            </div>
          </div>
        </body></html>
        """
    page = _page("https://ingatlan.com/35500142", html)

    result = public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[page],
    )

    assert result["queued"] == 0
    assert result["qualified"] == 0
    assert db.scalar(select(func.count()).select_from(GrowthSignal)) == 0
    assert db.scalar(select(func.count()).select_from(OutreachMessage)) == 0
    assert result["decisions"][0]["reasons"]


def test_hidden_contact_generic_address_and_nav_type_never_supply_evidence():
    hidden_email = _owner_html().replace(
        '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
        (
            '<div aria-hidden="true"><p>E-mail</p>'
            '<a href="mailto:kovacs.peter@example.test">E-mail</a></div>'
        ),
    )
    hidden_decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500102",
        html=hidden_email,
        response_sha256=hashlib.sha256(hidden_email.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert hidden_decision.signal is None
    assert "recipient_email_missing" in hidden_decision.reasons

    stylesheet_hidden_email = _owner_html().replace(
        '<a href="mailto:kovacs.peter@example.test">E-mail</a>',
        (
            "<style>.concealed-contact { display: none; }</style>"
            '<div class="concealed-contact"><p>E-mail</p>'
            '<a href="mailto:kovacs.peter@example.test">E-mail</a></div>'
        ),
    )
    stylesheet_hidden_decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500102-css",
        html=stylesheet_hidden_email,
        response_sha256=hashlib.sha256(stylesheet_hidden_email.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert stylesheet_hidden_decision.signal is None
    assert "recipient_email_missing" in stylesheet_hidden_decision.reasons

    generic_location = _owner_html().replace("Település", "Cím")
    location_decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500103",
        html=generic_location,
        response_sha256=hashlib.sha256(generic_location.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert location_decision.signal is None
    assert "listing_location_missing" in location_decision.reasons

    navigation_only = _owner_html().replace(
        "<h1>Eladó építési telek</h1>",
        "<h1>Eladó ingatlan</h1><nav>Építési telek</nav>",
    )
    type_decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500104",
        html=navigation_only,
        response_sha256=hashlib.sha256(navigation_only.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert type_decision.signal is None
    assert "building_plot_type_not_explicit" in type_decision.reasons


def test_http_200_tombstone_is_ineligible():
    html = _owner_html(extra="<p>Elkelt</p>")
    decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=_attempt(),
        listing_url="https://ingatlan.com/35500105",
        html=html,
        response_sha256=hashlib.sha256(html.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert decision.signal is None
    assert "listing_inactive_explicit" in decision.reasons


def test_blocked_agent_is_not_stored_or_queued(db, land_runtime):
    html = _agent_html(organization="GDN Ingatlanhálózat")
    result = public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page("https://ingatlan.com/35500003", html)],
    )

    assert result["qualified"] == 1 and result["queued"] == 0
    assert result["decisions"][0]["status"] == "blocked"
    assert result["decisions"][0]["reasons"] == ["land_agent_gdn_network_hard_gate"]
    assert not db.scalars(select(GrowthSignal)).all()
    assert not db.scalars(select(OutreachMessage)).all()


def test_direct_public_land_ingest_requires_complete_url_bound_evidence(db, land_runtime):
    html = _owner_html()
    attempt = _attempt()
    decision = public_land.listing_signal_decision(
        route=_route(),
        attempt=attempt,
        listing_url="https://ingatlan.com/35500120",
        html=html,
        response_sha256=hashlib.sha256(html.encode()).hexdigest(),
        source_id="construction_public_land_html",
    )
    assert decision.signal is not None
    with pytest.raises(GrowthRegistryError, match="public_land_source_evidence_required"):
        service.ingest_signal(db, decision.signal)
    assert db.scalar(select(func.count()).select_from(GrowthSignal)) == 0
    assert db.scalar(select(func.count()).select_from(OutreachMessage)) == 0

    evidence = [
        {
            **record,
            "source_url": "https://ingatlan.com/DIFFERENT-35500120",
            "snapshot_sha256": decision.signal.source_payload_hash,
            "fetched_at": attempt.completed_at,
        }
        for record in decision.evidence_records
    ]
    with pytest.raises(
        GrowthRegistryError,
        match="public_land_source_evidence_binding_mismatch",
    ):
        service.ingest_signal(db, decision.signal, source_evidence=evidence)
    assert db.scalar(select(func.count()).select_from(GrowthSignal)) == 0
    assert db.scalar(select(func.count()).select_from(OutreachMessage)) == 0


def test_evidence_manifest_tamper_blocks_before_provider(db, land_runtime, monkeypatch):
    html = _owner_html()
    public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page("https://ingatlan.com/35500121", html)],
    )
    evidence = db.scalar(
        select(GrowthSignalSourceEvidence).where(
            GrowthSignalSourceEvidence.field_name == "recipient_name"
        )
    )
    evidence.source_snippet = "tampered public snippet"
    db.commit()
    monkeypatch.setattr(
        service.SMTPEmailAdapter,
        "send",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not run after evidence tamper")
        ),
    )

    outreach = service.dispatch_outreach(db, _claim_for_dispatch(db))

    assert outreach.status == "blocked"
    assert outreach.last_error == "public_land_source_evidence_manifest_mismatch"


def test_dynamic_html_hash_change_passes_exact_live_fields_and_is_audited(
    db, land_runtime, monkeypatch
):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500122", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    signal = db.scalar(select(GrowthSignal))
    dynamic_html = html.replace("</body>", "<p>Megtekintések: 42</p></body>")
    dynamic_hash = hashlib.sha256(dynamic_html.encode()).hexdigest()
    assert dynamic_hash != page["response_sha256"]
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": dynamic_html,
            "response_sha256": dynamic_hash,
        },
    )

    revalidation = public_land.live_listing_revalidation(db, signal)

    assert revalidation.rejection_reason is None
    assert revalidation.audit_evidence["response_sha256"] == dynamic_hash
    assert revalidation.audit_evidence["status"] == "passed"
    assert {item["field_name"] for item in revalidation.audit_evidence["critical_fields"]} == {
        "listing_permalink",
        "recipient_name",
        "recipient_email",
        "recipient_role",
        "property_type",
        "location",
        "plot_size_sqm",
    }


def test_successful_dispatch_persists_attested_live_receipt(db, land_runtime, monkeypatch):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500123", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": html,
            "response_sha256": page["response_sha256"],
        },
    )

    def safe_send(*_args, pre_send_guard=None, **_kwargs):
        assert pre_send_guard is not None
        pre_send_guard()
        return EmailReceipt(
            provider_message_id="SYNTHETIC-MSG-1",
            accepted_recipient="kovacs.peter@example.test",
            provider="gmail_api",
            response_sha256="d" * 64,
            detail={
                "readback_verified": True,
                "readback_mime_sha256": "e" * 64,
                "rfc_message_id": "<synthetic@example.test>",
            },
        )

    monkeypatch.setattr(service.SMTPEmailAdapter, "send", safe_send)
    outreach = service.dispatch_outreach(db, _claim_for_dispatch(db))
    receipt = json.loads(outreach.receipt_json)

    assert outreach.status == "sent"
    live = receipt["live_listing_revalidation"]
    assert live["status"] == "passed"
    assert live["response_sha256"] == page["response_sha256"]
    assert len(live["attestation_hmac_sha256"]) == 64
    assert all(item["snippet_sha256"] for item in live["critical_fields"])


def test_live_refetch_change_blocks_dispatch_before_smtp(db, land_runtime, monkeypatch):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500004", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    signal = db.scalar(select(GrowthSignal))
    outreach = db.scalar(select(OutreachMessage))
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": html.replace("605", "606"),
            "response_sha256": "f" * 64,
        },
    )
    monkeypatch.setattr(
        service.SMTPEmailAdapter,
        "send",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("SMTP must not run after changed live evidence")
        ),
    )

    result = service.dispatch_outreach(db, _claim_for_dispatch(db, outreach))

    assert result.status == "blocked"
    assert result.last_error == "public_land_live_evidence_changed:plot_size_sqm"
    assert signal.status == "blocked"


def test_live_refetch_unavailable_blocks_dispatch_before_smtp(db, land_runtime, monkeypatch):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500006", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    signal = db.scalar(select(GrowthSignal))
    outreach = db.scalar(select(OutreachMessage))
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "failed",
            "http_status": 410,
            "error_type": "listing_unavailable",
        },
    )
    monkeypatch.setattr(
        service.SMTPEmailAdapter,
        "send",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("SMTP must not run after listing disappearance")
        ),
    )

    result = service.dispatch_outreach(db, _claim_for_dispatch(db, outreach))

    assert result.status == "blocked"
    assert result.last_error == "public_land_live_listing_unavailable:listing_unavailable"
    assert signal.status == "blocked"


def test_live_refetch_accepts_unchanged_complete_evidence(db, land_runtime, monkeypatch):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500007", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    signal = db.scalar(select(GrowthSignal))
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": html,
            "response_sha256": page["response_sha256"],
        },
    )

    assert public_land.live_listing_rejection_reason(db, signal) is None


def test_live_refetch_requires_complete_persisted_evidence(db, land_runtime, monkeypatch):
    html = _owner_html()
    page = _page("https://ingatlan.com/35500005", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    signal = db.scalar(select(GrowthSignal))
    missing = db.scalar(
        select(GrowthSignalSourceEvidence).where(
            GrowthSignalSourceEvidence.field_name == "recipient_email"
        )
    )
    db.delete(missing)
    db.commit()
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: (_ for _ in ()).throw(AssertionError("missing evidence blocks refetch")),
    )

    assert (
        public_land.live_listing_rejection_reason(db, signal)
        == "public_land_live_source_evidence_missing"
    )


def test_production_writes_require_only_exact_approved_writes_token(tmp_path, monkeypatch):
    gate = tmp_path / "growth-kill-switch"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            kill_switch_file=str(gate),
            runtime_kill_switch_file=str(tmp_path / "runtime-growth-kill-switch"),
        ),
    )

    gate.write_text("ALLOW_APPROVED_CANARY\n", encoding="utf-8")
    assert growth_registry.writes_unlocked() is False
    gate.write_text("ALLOW_APPROVED_WRITES\n", encoding="utf-8")
    assert growth_registry.writes_unlocked() is True


@pytest.mark.parametrize("configured_cap", ["4", "not-an-integer"])
def test_invalid_canary_cap_configuration_fails_closed(monkeypatch, configured_cap):
    monkeypatch.setenv(
        "LAND_OUTREACH_PRODUCTION_CANARY_MAX_TOTAL",
        configured_cap,
    )

    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_cap_invalid",
    ):
        service._land_canary_limit()


def test_land_canary_stops_at_three_without_changing_normal_rate_limits(db, land_runtime):
    canary_now = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)
    _set_canary_pending(db)
    for index in range(3):
        outreach_id = f"OUT-CANARY-{index}"
        service._claim_land_canary_slot(db, outreach_id, now=canary_now)
        service._finish_land_canary_slot(
            db,
            outreach_id,
            outcome="sent",
            provider_message_id=f"MSG-{index}",
        )
        db.commit()

    with pytest.raises(GrowthRegistryError, match="land_outreach_production_canary_cap_reached"):
        service._claim_land_canary_slot(db, "OUT-CANARY-4", now=canary_now)

    assert (
        db.scalar(
            select(func.count())
            .select_from(GrowthLandCanarySlot)
            .where(GrowthLandCanarySlot.status == "sent")
        )
        == 3
    )
    assert service._outreach_send_capacity(db) == 5


def test_canary_wrong_date_and_ambiguous_slots_stay_closed(db, land_runtime):
    _set_canary_pending(db)
    september_first = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_release_required",
    ):
        service._land_canary_scope(db, september_first)

    now = datetime.now(UTC)
    for index, slot in enumerate(
        db.scalars(select(GrowthLandCanarySlot).order_by(GrowthLandCanarySlot.slot_number)),
        start=1,
    ):
        slot.status = "consumed"
        slot.outreach_id = f"OUT-EXPLICIT-{index}"
        slot.claimed_at = now
        slot.sent_at = now
    state = db.get(GrowthLandCanaryState, 1)
    assert state is not None
    state.status = "completed"
    db.commit()

    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_verified_delivery_required",
    ):
        service.release_land_canary(
            db,
            approved_by="synthetic-reviewer",
            now=september_first,
        )

    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_release_required",
    ):
        service._land_canary_scope(db, september_first)


def test_canary_release_requires_three_verified_sends_and_next_budapest_day(db, land_runtime):
    pages = [
        _page(
            f"https://ingatlan.com/{35500160 + index}",
            _owner_html(
                name=f"Minta Tulajdonos {index}",
                email=f"minta.tulajdonos{index}@example.test",
                location=f"Mintahelység {index}",
                plot_size_sqm=700 + index,
            ),
        )
        for index in range(3)
    ]
    result = public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=pages,
    )
    assert result["queued"] == 3
    _set_canary_pending(db)
    sent_at = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)
    messages = list(db.scalars(select(OutreachMessage).order_by(OutreachMessage.id)))
    slots = list(
        db.scalars(select(GrowthLandCanarySlot).order_by(GrowthLandCanarySlot.slot_number))
    )
    for index, (slot, outreach) in enumerate(zip(slots, messages, strict=True), start=1):
        provider_message_id = f"SYNTHETIC-CANARY-{index}"
        mime_sha256 = hashlib.sha256(provider_message_id.encode()).hexdigest()
        outreach.status = "sent"
        outreach.sent_at = sent_at
        outreach.provider_message_id = provider_message_id
        outreach.receipt_json = service.canonical_json(
            {
                "provider": "gmail_api",
                "accepted": True,
                "response_sha256": mime_sha256,
                "delivery_detail": {
                    "readback_verified": True,
                    "readback_mime_sha256": mime_sha256,
                    "rfc_message_id": f"<synthetic-canary-{index}@example.test>",
                    "label_ids": ["SENT"],
                    "provider_message_id": provider_message_id,
                },
            }
        )
        slot.status = "sent"
        slot.outreach_id = outreach.outreach_id
        slot.claimed_at = sent_at
        slot.sent_at = sent_at
        slot.provider_message_id = provider_message_id
    state = db.get(GrowthLandCanaryState, 1)
    assert state is not None
    state.status = "completed"
    db.commit()

    original_receipt = messages[0].receipt_json
    incomplete_receipt = json.loads(original_receipt)
    incomplete_receipt["delivery_detail"]["label_ids"] = []
    messages[0].receipt_json = service.canonical_json(incomplete_receipt)
    db.flush()
    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_verified_delivery_required",
    ):
        service.release_land_canary(
            db,
            approved_by="synthetic-reviewer",
            now=datetime(2026, 9, 1, 8, 0, tzinfo=UTC),
        )
    messages[0].receipt_json = original_receipt
    messages[0].status = "delivered"
    messages[1].status = "responded"
    db.flush()

    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_release_too_early",
    ):
        service.release_land_canary(
            db,
            approved_by="synthetic-reviewer",
            now=datetime(2026, 8, 31, 20, 0, tzinfo=UTC),
        )

    september_first = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    released = service.release_land_canary(
        db,
        approved_by="synthetic-reviewer",
        now=september_first,
    )

    assert released.status == "released"
    assert service._land_canary_scope(db, september_first) == (
        3,
        date(2026, 8, 31),
        False,
    )


def test_canary_missing_slot_fails_closed(db, land_runtime):
    _set_canary_pending(db)
    slot = db.scalar(select(GrowthLandCanarySlot).where(GrowthLandCanarySlot.slot_number == 3))
    db.delete(slot)
    db.commit()

    with pytest.raises(
        GrowthRegistryError,
        match="land_outreach_production_canary_slots_invalid",
    ):
        service._claim_land_canary_slot(
            db,
            "OUT-MISSING-SLOT",
            now=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
        )


def test_canary_backfill_ignores_non_land_growth_delivery(db, land_runtime):
    _set_canary_pending(db)
    html = _owner_html()
    public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page("https://ingatlan.com/35500129", html)],
    )
    signal = db.scalar(select(GrowthSignal))
    outreach = db.scalar(select(OutreachMessage))
    assert outreach is not None
    signal.signal_type = "synthetic_non_land"
    signal.contact_basis = "public_business_contact"
    outreach.status = "sent"
    outreach.sent_at = datetime(2026, 8, 31, 6, 0, tzinfo=UTC)
    db.commit()

    assert service._claim_land_canary_slot(
        db,
        "OUT-NEW-LAND",
        now=datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
    )
    slots = list(
        db.scalars(select(GrowthLandCanarySlot).order_by(GrowthLandCanarySlot.slot_number))
    )

    assert [slot.status for slot in slots] == ["claimed", "available", "available"]
    assert slots[0].outreach_id == "OUT-NEW-LAND"


def test_crash_after_provider_guard_leaves_durable_claimed_canary_slot(
    db, land_runtime, monkeypatch
):
    _set_canary_pending(db)
    monkeypatch.setattr(
        service,
        "_land_canary_scope",
        lambda *_args, **_kwargs: (3, date(2026, 8, 31), True),
    )
    html = _owner_html()
    page = _page("https://ingatlan.com/35500130", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": html,
            "response_sha256": page["response_sha256"],
        },
    )

    def crash_after_guard(*_args, pre_send_guard=None, **_kwargs):
        assert pre_send_guard is not None
        pre_send_guard()
        raise SystemExit("synthetic crash after POST boundary")

    monkeypatch.setattr(service.SMTPEmailAdapter, "send", crash_after_guard)
    outreach = _claim_for_dispatch(db)
    with pytest.raises(SystemExit, match="synthetic crash"):
        service.dispatch_outreach(db, outreach)
    db.expire_all()

    slot = db.scalar(
        select(GrowthLandCanarySlot).where(GrowthLandCanarySlot.outreach_id == outreach.outreach_id)
    )
    assert slot is not None
    assert slot.status == "claimed"
    assert slot.claimed_at is not None and slot.sent_at is None


def test_transport_attempted_unknown_consumes_canary_slot(db, land_runtime, monkeypatch):
    _set_canary_pending(db)
    monkeypatch.setattr(
        service,
        "_land_canary_scope",
        lambda *_args, **_kwargs: (3, date(2026, 8, 31), True),
    )
    html = _owner_html()
    page = _page("https://ingatlan.com/35500131", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": html,
            "response_sha256": page["response_sha256"],
        },
    )

    def ambiguous_transport(*_args, pre_send_guard=None, **_kwargs):
        assert pre_send_guard is not None
        pre_send_guard()
        raise EmailDeliveryError(
            "gmail_api_http_500",
            retry_safe=False,
            transport_attempted=True,
        )

    monkeypatch.setattr(service.SMTPEmailAdapter, "send", ambiguous_transport)
    outreach = service.dispatch_outreach(db, _claim_for_dispatch(db))
    slot = db.scalar(
        select(GrowthLandCanarySlot).where(GrowthLandCanarySlot.outreach_id == outreach.outreach_id)
    )

    assert outreach.status == "claimed"
    assert slot is not None and slot.status == "consumed"


def test_fourth_canary_message_remains_retryable_without_provider(db, land_runtime, monkeypatch):
    _set_canary_pending(db)
    monkeypatch.setattr(
        service,
        "_land_canary_scope",
        lambda *_args, **_kwargs: (3, date(2026, 8, 31), True),
    )
    now = datetime.now(UTC)
    for index, slot in enumerate(
        db.scalars(select(GrowthLandCanarySlot).order_by(GrowthLandCanarySlot.slot_number)),
        start=1,
    ):
        slot.status = "consumed"
        slot.outreach_id = f"OUT-USED-{index}"
        slot.claimed_at = now
        slot.sent_at = now
    state = db.get(GrowthLandCanaryState, 1)
    assert state is not None
    state.status = "completed"
    db.commit()
    html = _owner_html()
    page = _page("https://ingatlan.com/35500132", html)
    public_land.process_public_land_listings(
        db, route=_route(), attempt=_attempt(), listing_pages=[page]
    )
    monkeypatch.setattr(
        "app.growth_ops.catalog.fetch_public_land_listing_url",
        lambda _url: {
            "status": "succeeded",
            "url": page["url"],
            "html": html,
            "response_sha256": page["response_sha256"],
        },
    )
    monkeypatch.setattr(
        service.SMTPEmailAdapter,
        "send",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not run above canary cap")
        ),
    )

    outreach = service.dispatch_outreach(db, _claim_for_dispatch(db))

    assert outreach.status == "queued"
    assert outreach.last_error == "land_outreach_production_canary_cap_reached"


def test_growth_registry_template_carries_exact_enabled_public_land_binding():
    template_path = (
        Path(__file__).resolve().parents[3] / "config" / "growth" / "registry.template.json"
    )
    payload = json.loads(template_path.read_text(encoding="utf-8"))

    assert payload["sources"]["construction_public_land_html"] == {
        "enabled": True,
        "kind": "public_land_listing_html",
        "fetch_mode": "ingest_only",
        "motor": "construction",
        "bucket": "property_development",
        "route_set_sha256": managed_public_land_route_set_sha256(),
    }


def test_public_land_route_ensure_is_dry_run_idempotent_and_readable(db):
    db.add(
        SourceCatalogRevision(
            revision_id="SCR-LAND-ROUTES",
            spreadsheet_id="sheet",
            sheet_id=1,
            source_modified_time="2026-08-30T00:00:00Z",
            catalog_sha256="c" * 64,
            route_count=1,
            status="active",
            imported_at=datetime.now(UTC),
        )
    )
    db.add(
        SourceCoverageRoute(
            route_key="CANONICAL-BASELINE-1",
            route_id="CANONICAL-BASELINE-1",
            catalog_sha256="c" * 64,
            motor="construction",
            route_url="https://example.com/canonical-route",
            source_row_sha256="d" * 64,
            source_record_json="{}",
            enabled=True,
        )
    )
    db.commit()

    dry_run = ensure_public_html_land_routes(db, dry_run=True)
    assert dry_run["planned"] == 7 and dry_run["create"] == 7
    assert db.scalar(select(func.count()).select_from(SourceCoverageRoute)) == 1

    applied = ensure_public_html_land_routes(db, dry_run=False)
    repeated = ensure_public_html_land_routes(db, dry_run=False)

    assert applied["readback_pass"] is True and applied["create"] == 7
    assert repeated["readback_pass"] is True and repeated["unchanged"] == 7
    assert db.scalar(select(func.count()).select_from(SourceCoverageRoute)) == 8
    revision = db.scalar(select(SourceCatalogRevision))
    assert revision.route_count == 1
    assert (
        db.scalar(
            select(func.count())
            .select_from(SourceCoverageRoute)
            .where(SourceCoverageRoute.catalog_sha256 == "c" * 64)
        )
        == 1
    )
    route_state = public_land_route_readiness(db)
    assert route_state["ready"] is True
    assert route_state["ready_count"] == 7
    assert route_state["route_set_sha256"] == managed_public_land_route_set_sha256()


def test_public_land_route_ensure_plans_and_retires_unexpected_managed_route(db):
    ensure_public_html_land_routes(db, dry_run=False)
    unexpected = SourceCoverageRoute(
        route_key="LAND-PUBLIC-HTML:unexpected",
        route_id="LAND-PUBLIC-UNEXPECTED",
        catalog_sha256="e" * 64,
        motor="construction",
        category="residential_building_plot",
        source_name="unexpected",
        source_type="public_html",
        route_url="https://example.com/elado-telek",
        catalog_status="active",
        source_row_sha256="f" * 64,
        source_record_json="{}",
        enabled=True,
    )
    db.add(unexpected)
    db.commit()

    before = public_land_route_readiness(db)
    dry_run = ensure_public_html_land_routes(db, dry_run=True)

    assert before["ready"] is False
    assert before["unexpected_active_routes"] == [unexpected.route_key]
    assert dry_run["disabled_duplicates"] == [
        {
            "route_key": unexpected.route_key,
            "portal": "unknown",
            "reason": "unexpected_managed_route",
        }
    ]
    db.refresh(unexpected)
    assert unexpected.enabled is True

    applied = ensure_public_html_land_routes(db, dry_run=False)
    db.refresh(unexpected)

    assert applied["readback_pass"] is True
    assert unexpected.enabled is False
    assert unexpected.catalog_status == "retired"
    assert public_land_route_readiness(db)["ready"] is True


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "wrong_url",
        "duplicate",
        "wrong_source_row_sha",
        "wrong_source_record",
        "wrong_motor",
        "wrong_validation",
    ],
)
def test_public_land_route_readiness_requires_exact_seven_bindings(db, mutation):
    ensure_public_html_land_routes(db, dry_run=False)
    first = db.scalar(
        select(SourceCoverageRoute)
        .where(SourceCoverageRoute.route_key.like("LAND-PUBLIC-HTML:%"))
        .order_by(SourceCoverageRoute.route_key)
    )
    assert first is not None
    if mutation == "missing":
        db.delete(first)
    elif mutation == "wrong_url":
        first.route_url = "https://example.com/not-the-managed-category"
    elif mutation == "duplicate":
        db.add(
            SourceCoverageRoute(
                route_key="LEGACY-PUBLIC-LAND-DUPLICATE",
                route_id="LEGACY-PUBLIC-LAND-DUPLICATE",
                catalog_sha256="e" * 64,
                motor="construction",
                category="residential_building_plot",
                source_name="legacy-duplicate",
                source_type="public_html",
                route_url=first.route_url,
                catalog_status="active",
                source_row_sha256="f" * 64,
                source_record_json="{}",
                enabled=True,
            )
        )
    elif mutation == "wrong_source_row_sha":
        first.source_row_sha256 = "0" * 64
    elif mutation == "wrong_source_record":
        first.source_record_json = '{"tampered":true}'
        first.source_row_sha256 = hashlib.sha256(first.source_record_json.encode()).hexdigest()
    elif mutation == "wrong_motor":
        first.motor = "tampered-motor"
    else:
        first.validation = "tampered-validation"
    db.commit()

    state = public_land_route_readiness(db)

    assert state["ready"] is False
    assert state["ready_count"] == 6
    assert any(not item["ready"] for item in state["routes"])


@pytest.mark.parametrize("mutation", ["unexpected_route_key", "wrong_route_digest"])
def test_managed_scanner_refuses_non_exact_route_set(
    db, land_runtime, monkeypatch, mutation
):
    if mutation == "unexpected_route_key":
        db.add(
            SourceCoverageRoute(
                route_key="LAND-PUBLIC-HTML:aaa-unexpected",
                route_id="LAND-PUBLIC-AAA-UNEXPECTED",
                catalog_sha256=managed_public_land_route_set_sha256(),
                motor="construction",
                category="residential_building_plot",
                source_name="unexpected",
                source_type="public_html",
                route_url="https://example.com/elado-telek",
                catalog_status="active",
                source_row_sha256="f" * 64,
                source_record_json="{}",
                enabled=True,
            )
        )
    else:
        route = db.scalar(
            select(SourceCoverageRoute).where(
                SourceCoverageRoute.route_key == "LAND-PUBLIC-HTML:dh"
            )
        )
        assert route is not None
        route.catalog_sha256 = "0" * 64
    db.commit()
    monkeypatch.setattr(
        catalog,
        "settings",
        lambda: SimpleNamespace(
            canonical_wide_enabled=True,
            canonical_route_scanning_enabled=True,
            timezone="Europe/Budapest",
            canonical_daily_at="05:30",
            canonical_route_batch_size=0,
            canonical_processing_enabled=True,
        ),
    )
    monkeypatch.setattr(
        catalog,
        "active_revision",
        lambda _db: SimpleNamespace(catalog_sha256="c" * 64),
    )
    monkeypatch.setattr(
        catalog,
        "_fetch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no managed route may be fetched before exact route readback")
        ),
    )

    result = catalog.scan_due_routes(
        db,
        now=datetime(2026, 8, 30, 6, 0, tzinfo=UTC),
    )

    assert result["land_public_lane"]["attempted"] == 0
    assert result["land_public_lane"]["route_readiness"]["ready"] is False


def test_public_land_send_readiness_needs_no_json_or_rss_source(db, land_runtime):
    ensure_public_html_land_routes(db, dry_run=False)
    source = dict(_Registry.sources["construction_public_land_html"])
    land_only_registry = SimpleNamespace(sources={"construction_public_land_html": source})
    state = service._outbound_send_readiness_state(db, land_only_registry)

    assert state["ready"] is True
    assert state["scheduled_enabled_sources"] == 0
    assert state["managed_land_source"]["ready"] is True
    assert state["managed_land_routes"]["ready"] is True

    html = _owner_html()
    public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page("https://ingatlan.com/35500140", html)],
    )
    signal = db.scalar(select(GrowthSignal))
    assert service._authoritative_send_readiness_reason(db, land_only_registry, signal) is None
    signal.signal_type = "synthetic_non_land"
    assert (
        service._authoritative_send_readiness_reason(db, land_only_registry, signal)
        == "growth_scheduled_source_missing"
    )


@pytest.mark.parametrize("readiness_failure", ["managed_route", "sender"])
def test_preclaim_readiness_failure_preserves_queue_and_attempt_budget(
    db, land_runtime, monkeypatch, readiness_failure
):
    public_land.process_public_land_listings(
        db,
        route=_route(),
        attempt=_attempt(),
        listing_pages=[_page("https://ingatlan.com/35500141", _owner_html())],
    )
    outreach = db.scalar(select(OutreachMessage))
    assert outreach is not None
    if readiness_failure == "managed_route":
        managed_route = db.scalar(
            select(SourceCoverageRoute).where(
                SourceCoverageRoute.route_key.like("LAND-PUBLIC-HTML:%")
            )
        )
        assert managed_route is not None
        db.delete(managed_route)
    else:
        sender = db.scalar(
            select(MailSendingDomain).where(MailSendingDomain.domain_key == "imperial-test")
        )
        assert sender is not None
        sender.active = False
    db.commit()
    provider_calls = 0

    def fail_if_called(*_args, **_kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider must not run when pre-claim readiness fails")

    monkeypatch.setattr(service, "_outreach_sending_window_open", lambda: True)
    monkeypatch.setattr(service, "_outreach_send_capacity", lambda _db, _now=None: 1)
    monkeypatch.setattr(service.SMTPEmailAdapter, "send", fail_if_called)

    assert service.dispatch_batch(db, limit=1) == 0
    db.refresh(outreach)
    assert outreach.status == "queued"
    assert outreach.attempt_count == 0
    assert outreach.claimed_by is None
    assert outreach.claimed_at is None
    assert outreach.lease_expires_at is None
    assert provider_calls == 0


@pytest.mark.parametrize(
    ("source_mutation", "reason"),
    [
        ("missing", "managed_land_source_binding_missing"),
        ("disabled", "managed_land_source_binding_missing"),
        ("wrong_kind", "managed_land_source_binding_invalid"),
        ("wrong_digest", "managed_land_source_binding_invalid"),
        ("duplicate", "managed_land_source_binding_not_unique"),
    ],
)
def test_managed_ingest_only_source_binding_is_exact(db, land_runtime, source_mutation, reason):
    ensure_public_html_land_routes(db, dry_run=False)
    sources = {
        "construction_public_land_html": dict(_Registry.sources["construction_public_land_html"])
    }
    if source_mutation == "missing":
        sources = {}
    elif source_mutation == "disabled":
        sources["construction_public_land_html"]["enabled"] = False
    elif source_mutation == "wrong_kind":
        sources["construction_public_land_html"]["kind"] = "json"
    elif source_mutation == "wrong_digest":
        sources["construction_public_land_html"]["route_set_sha256"] = "0" * 64
    else:
        sources["second_land_ingest"] = {
            **sources["construction_public_land_html"],
            "enabled": True,
        }

    state = service._outbound_send_readiness_state(db, SimpleNamespace(sources=sources))

    assert state["ready"] is False
    assert state["reason"] == reason


def test_public_portal_listing_discovery_is_same_host_and_bounded(tmp_path, monkeypatch):
    registry_path = tmp_path / "portals.json"
    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "portals": [
                    {
                        "key": "ingatlan_com",
                        "domains": ["ingatlan.com"],
                        "category_url": "https://www.ingatlan.com/elado+telek",
                        "discovery_mode": "public_html",
                        "publish_mode": "manual",
                        "discovery_enabled": True,
                        "publish_enabled": False,
                        "adapter_module": None,
                        "respect_robots_txt": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LAND_ACQUISITION_PORTAL_REGISTRY_FILE", str(registry_path))
    streamed: list[str] = []
    monkeypatch.setattr(
        catalog,
        "_fresh_pinned_robots_error",
        lambda *_args, **_kwargs: None,
    )

    def pinned(url, **_kwargs):
        streamed.append(url)
        if url.endswith("elado+telek"):
            links = "".join(
                f'<a href="https://www.ingatlan.com/{35500010 + index}">Telek {index}</a>'
                for index in range(5)
            )
            body = f"<html><body>{links}</body></html>".encode()
        else:
            body = _owner_html().encode()
        return {
            "status_code": 200,
            "headers": {"content-type": "text/html; charset=utf-8"},
            "body": body,
            "source_ip": "93.184.216.34",
        }

    monkeypatch.setattr(catalog, "_pinned_https_get", pinned)
    result = catalog._fetch(
        SimpleNamespace(
            route_url="https://www.ingatlan.com/elado+telek",
            source_record_json="{}",
        ),
        managed_land=True,
    )

    assert result["status"] == "succeeded"
    assert len(result["land_listing_pages"]) == 3
    assert streamed == [
        "https://www.ingatlan.com/elado+telek",
        "https://www.ingatlan.com/35500010",
        "https://www.ingatlan.com/35500011",
        "https://www.ingatlan.com/35500012",
    ]


def test_pinned_fetch_resolves_once_and_preserves_original_tls_host(monkeypatch):
    dns_calls = 0
    connected: list[tuple[str, int]] = []
    requests: list[tuple[str, str, dict[str, str]]] = []

    def rebinding_dns(*_args, **_kwargs):
        nonlocal dns_calls
        dns_calls += 1
        address = "93.184.216.34" if dns_calls == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (address, 443))]

    class RawSocket:
        def settimeout(self, _value):
            return None

        def close(self):
            return None

    class TLSContext:
        def wrap_socket(self, raw, *, server_hostname):
            assert server_hostname == "www.ingatlan.com"
            return raw

    class Response:
        status = 200

        def __init__(self):
            self.sent = False

        def getheaders(self):
            return [
                ("Content-Type", "text/html"),
                ("Content-Encoding", "identity"),
            ]

        def read(self, _size):
            if self.sent:
                return b""
            self.sent = True
            return b"<html>ok</html>"

    class Connection:
        def __init__(self, host, **_kwargs):
            assert host == "www.ingatlan.com"
            self.sock = None

        def request(self, method, path, headers):
            requests.append((method, path, headers))

        def getresponse(self):
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(catalog.socket, "getaddrinfo", rebinding_dns)
    monkeypatch.setattr(
        catalog.socket,
        "create_connection",
        lambda address, **_kwargs: connected.append(address) or RawSocket(),
    )
    monkeypatch.setattr(catalog.ssl, "create_default_context", TLSContext)
    monkeypatch.setattr(catalog.http.client, "HTTPSConnection", Connection)

    result = catalog._pinned_https_get(
        "https://www.ingatlan.com/35500150",
        max_response_bytes=10_000,
        deadline_monotonic=catalog.monotonic_time.monotonic() + 5,
    )

    assert dns_calls == 1
    assert connected == [("93.184.216.34", 443)]
    assert result["source_ip"] == "93.184.216.34"
    assert requests[0][2]["Host"] == "www.ingatlan.com"
    assert requests[0][2]["Accept-Encoding"] == "identity"


def test_listing_redirect_and_non_identity_encoding_fail_closed(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "_fresh_pinned_robots_error",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        catalog,
        "_pinned_https_get",
        lambda *_args, **_kwargs: {
            "status_code": 302,
            "headers": {"content-type": "text/html", "location": "https://example.com"},
            "body": b"redirect",
            "source_ip": "93.184.216.34",
        },
    )
    result = catalog.fetch_public_land_listing_url("https://ingatlan.com/35500151")
    assert result["status"] == "blocked"
    assert result["error_type"] == "blocked_page"

    monkeypatch.setattr(
        catalog,
        "_pinned_https_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            catalog.UnsafeRouteError("response_compression_forbidden")
        ),
    )
    compressed = catalog.fetch_public_land_listing_url("https://ingatlan.com/35500152")
    assert compressed == {
        "status": "blocked",
        "error_type": "response_compression_forbidden",
    }


def test_dispatch_listing_refetch_uses_fresh_robots_readback_each_time(monkeypatch):
    robots_calls = 0

    def fresh_robots(*_args, **_kwargs):
        nonlocal robots_calls
        robots_calls += 1
        return None

    html = _owner_html().encode()
    monkeypatch.setattr(catalog, "_fresh_pinned_robots_error", fresh_robots)
    monkeypatch.setattr(
        catalog,
        "_pinned_https_get",
        lambda *_args, **_kwargs: {
            "status_code": 200,
            "headers": {"content-type": "text/html"},
            "body": html,
            "source_ip": "93.184.216.34",
        },
    )

    first = catalog.fetch_public_land_listing_url("https://ingatlan.com/35500153")
    second = catalog.fetch_public_land_listing_url("https://ingatlan.com/35500153")

    assert first["status"] == second["status"] == "succeeded"
    assert robots_calls == 2


def test_managed_lane_persists_cursor_and_reaches_fourth_candidate_next_batch(
    db, land_runtime, monkeypatch
):
    fourth_url = "https://ingatlan.com/35500999"
    first_three = [f"https://ingatlan.com/{35500996 + index}" for index in range(3)]
    calls: list[tuple[str, list[str], set[str]]] = []
    target_calls = 0

    monkeypatch.setattr(
        catalog,
        "settings",
        lambda: SimpleNamespace(
            canonical_wide_enabled=True,
            canonical_route_scanning_enabled=True,
            timezone="Europe/Budapest",
            canonical_daily_at="05:30",
            canonical_route_batch_size=0,
            canonical_processing_enabled=True,
        ),
    )
    monkeypatch.setattr(
        catalog,
        "active_revision",
        lambda _db: SimpleNamespace(catalog_sha256="c" * 64),
    )

    def fake_fetch(
        route,
        *,
        managed_land=False,
        pending_listing_urls=None,
        examined_listing_urls=None,
    ):
        nonlocal target_calls
        pending = list(pending_listing_urls or [])
        examined = set(examined_listing_urls or set())
        calls.append((route.route_key, pending, examined))
        common = {
            "status": "succeeded",
            "http_status": 200,
            "response_sha256": "a" * 64,
            "analysis_text": "",
            "analysis_links": [],
        }
        if route.route_key != "LAND-PUBLIC-HTML:ingatlan_com":
            return {
                **common,
                "evidence": {"land_listing_fetches": []},
                "land_listing_pages": [],
                "land_listing_candidates": [],
                "land_listing_exhausted": True,
            }
        target_calls += 1
        if target_calls == 1:
            return {
                **common,
                "evidence": {
                    "land_listing_fetches": [
                        {
                            "url": url,
                            "status": "blocked",
                            "error_type": "blocked_page",
                        }
                        for url in first_three
                    ]
                },
                "land_listing_pages": [],
                "land_listing_candidates": [*first_three, fourth_url],
                "land_listing_exhausted": False,
            }
        if target_calls == 2:
            assert pending == [fourth_url]
            assert examined == set(first_three)
            return {
                **common,
                "evidence": {
                    "land_listing_fetches": [
                        {
                            "url": fourth_url,
                            "status": "succeeded",
                            "error_type": None,
                        }
                    ]
                },
                "land_listing_pages": [_page(fourth_url, _owner_html())],
                "land_listing_candidates": [fourth_url],
                "land_listing_exhausted": True,
            }
        assert pending == first_three
        assert examined == {fourth_url}
        return {
            **common,
            "evidence": {
                "land_listing_fetches": [
                    {
                        "url": url,
                        "status": "blocked",
                        "error_type": "blocked_page",
                    }
                    for url in first_three
                ]
            },
            "land_listing_pages": [],
            "land_listing_candidates": first_three,
            "land_listing_exhausted": True,
        }

    monkeypatch.setattr(catalog, "_fetch", fake_fetch)
    first_run = catalog.scan_due_routes(
        db,
        now=datetime(2026, 8, 30, 6, 0, tzinfo=UTC),
    )
    second_run = catalog.scan_due_routes(
        db,
        now=datetime(2026, 8, 30, 6, 5, tzinfo=UTC),
    )
    third_run = catalog.scan_due_routes(
        db,
        now=datetime(2026, 9, 1, 6, 5, tzinfo=UTC),
    )

    cursors = list(
        db.scalars(
            select(GrowthPublicLandListingCursor).where(
                GrowthPublicLandListingCursor.route_key == "LAND-PUBLIC-HTML:ingatlan_com"
            )
        )
    )
    by_url = {row.listing_url: row for row in cursors}
    assert first_run["land_public_lane"]["attempted"] == 7
    assert first_run["land_public_lane"]["examined"] == 3
    assert first_run["land_public_lane"]["cursor"]["exhausted"] is False
    assert second_run["land_public_lane"]["attempted"] == 1
    assert second_run["land_public_lane"]["examined"] == 1
    assert second_run["land_public_lane"]["eligible"] == 1
    assert third_run["land_public_lane"]["attempted"] == 7
    assert third_run["land_public_lane"]["examined"] == 3
    assert by_url[fourth_url].status == "examined"
    assert all(by_url[url].status == "retryable" for url in first_three)
    assert target_calls == 3
