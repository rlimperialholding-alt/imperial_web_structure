from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.growth_ops import connectors, email as email_mod, registry as growth_registry
from app.growth_ops import service
from app.growth_ops.connectors import SourceBatch, SourceError
from app.growth_ops.email import EmailDeliveryError, EmailReceipt, SMTPEmailAdapter
from app.growth_ops.models import (
    GrowthControlState,
    GrowthRun,
    GrowthSignal,
    GrowthWorkerHeartbeat,
    OutreachMessage,
)
from app.growth_ops.registry import BrandBinding, GrowthRegistry, GrowthRegistryError
from app.growth_ops.schemas import GrowthSignalIn
from app.models import MailSendingDomain, MailSuppression
from synthetic_fixtures import synthetic_auth_value


def _job_token() -> str:
    return synthetic_auth_value("growth-ops", "job")

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _signal(**changes) -> GrowthSignalIn:
    payload = {
        "source_id": "construction-etdr",
        "external_key": "ETDR-2026-0001",
        "motor_key": "construction",
        "source_bucket": "etdr",
        "signal_type": "residential_construction",
        "detected_at": datetime.now(UTC) - timedelta(hours=1),
        "company_name": "Minta Építő Kft.",
        "company_registration_id": "01-09-999999",
        "subject_type": "organization",
        "recipient_email": "iroda@minta-epito.test",
        "recipient_email_type": "role",
        "contact_basis": "public_business_contact",
        "public_contact_url": "https://minta-epito.test/kapcsolat",
        "location": "Budapest",
        "summary": "Nyilvánosan közzétett új lakóépület építési jelzés.",
        "evidence_url": "https://source.test/etdr/2026-0001",
        "confidence": 90,
        "urgency": 80,
        "source_payload_hash": hashlib.sha256(b"source-row").hexdigest(),
    }
    payload.update(changes)
    return GrowthSignalIn.model_validate(payload)


def _body_template() -> str:
    return (
        "{company_name}! Releváns üzleti jelzés: {signal_summary}. "
        "Forrás: {evidence_url}. Kapcsolatfelvétel válaszban. "
        "Leiratkozás: {unsubscribe_url}"
    )


def _default_binding_config() -> dict:
    body = _body_template()
    return {
        "brand_name": "Bautica",
        "templates": {
            "default": {
                "initial": {"subject": "Szakmai egyeztetés", "body": body},
                "followup_1": {"subject": "Rövid utánkövetés", "body": body},
                "followup_2": {"subject": "Utolsó utánkövetés", "body": body},
            }
        },
        "followup_delays_days": [4, 8],
        "recipient_cooldown_days": 30,
        "max_daily_messages": 100,
        "reply_to": "info@bautica.test",
    }


class FakeGrowthRegistry:
    """In-memory stand-in for the managed growth registry (network-free)."""

    def __init__(self, *, motors=None, sources=None) -> None:
        self.motors = motors if motors is not None else {
            "construction": {
                "interval_minutes": 60,
                "max_raw_signals_per_run": 100,
                "daily_raw_review_target": 300,
            }
        }
        self.brands = {"bautica": {}}
        self.sources = sources if sources is not None else {
            "construction-etdr": {
                "motor": "construction",
                "bucket": "etdr",
                "enabled": True,
            },
            "construction-public_request": {
                "motor": "construction",
                "bucket": "public_request",
                "enabled": True,
            },
        }
        self.binding_config = _default_binding_config()
        self.fail_brand_binding = False

    def sources_for(self, motor_key: str):
        return [
            (source_id, dict(source))
            for source_id, source in sorted(self.sources.items())
            if source.get("motor") == motor_key and source.get("enabled")
        ]

    def validate_signal_source(self, *, source_id, motor_key, source_bucket) -> None:
        source = self.sources.get(source_id)
        if (
            not source
            or not source.get("enabled")
            or source.get("motor") != motor_key
            or source.get("bucket") != source_bucket
        ):
            raise GrowthRegistryError("source mismatch")

    def brand_for(self, signal_type: str, requested: str | None = None) -> str:
        routed = {"residential_construction": "bautica"}.get(signal_type, "")
        if requested and requested != routed:
            raise GrowthRegistryError("route mismatch")
        if not routed:
            raise GrowthRegistryError("no route")
        return routed

    def brand_binding(self, brand_id: str) -> BrandBinding:
        if self.fail_brand_binding:
            raise GrowthRegistryError("unknown brand")
        assert brand_id == "bautica"
        return BrandBinding(
            brand_id="bautica",
            sender_email="info@bautica.test",
            domain_key="bautica-test",
            secret={
                "host": "smtp.bautica.test",
                "port": 465,
                "username": "test",
                "password": synthetic_auth_value("bautica", "binding"),
                "use_ssl": True,
            },
            config=self.binding_config,
        )

    def readiness(self) -> dict:
        return {
            "version": "test-v1",
            "writes_unlocked": True,
            "motors": sorted(self.motors),
            "brands": sorted(self.brands),
            "enabled_sources": sum(bool(s.get("enabled")) for s in self.sources.values()),
            "ready": True,
        }


class FakeSMTPAdapter:
    """Stand-in for SMTPEmailAdapter used by the dispatch pipeline."""

    calls: list[dict] = []
    fail: Exception | None = None

    def __init__(self, binding) -> None:
        self.binding = binding

    def preflight(self) -> None:
        pass

    def send(self, **kwargs) -> EmailReceipt:
        FakeSMTPAdapter.calls.append(kwargs)
        if FakeSMTPAdapter.fail is not None:
            raise FakeSMTPAdapter.fail
        return EmailReceipt(
            provider_message_id="<msgid-1234@bautica.test>",
            accepted_recipient=kwargs["to_email"],
            provider="smtp",
            response_sha256="a" * 64,
            detail={"accepted": True},
        )


@pytest.fixture
def growth_runtime(monkeypatch, db):
    FakeSMTPAdapter.calls = []
    FakeSMTPAdapter.fail = None
    registry = FakeGrowthRegistry()
    monkeypatch.setattr(service.GrowthRegistry, "load", classmethod(lambda cls: registry))
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
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
        ),
    )
    monkeypatch.setattr(service, "SMTPEmailAdapter", FakeSMTPAdapter)
    db.add(
        MailSendingDomain(
            domain_key="bautica-test",
            domain_name="bautica.test",
            from_email="info@bautica.test",
            provider="smtp",
            spf_status="pass",
            dkim_status="pass",
            dmarc_status="pass",
            active=True,
        )
    )
    db.commit()
    return registry


def _outreach_row(db, *, status: str = "queued", attempt_count: int = 0, **kw) -> OutreachMessage:
    outreach_id = kw.pop("outreach_id", f"OUT-TEST-{abs(hash(repr(kw)))}")
    values = {
        "outreach_id": outreach_id,
        "signal_id": kw.pop("signal_id", "SIG-TEST-0001"),
        "motor_key": "construction",
        "brand_id": "bautica",
        "sender_email": "info@bautica.test",
        "recipient_email": "iroda@minta-epito.test",
        "sequence_step": 0,
        "subject": "Szakmai egyeztetés",
        "body_text": "Részletes, hasznos szöveg a leiratkozási linkkel együtt.",
        "unsubscribe_token_hash": hashlib.sha256(outreach_id.encode()).hexdigest(),
        "idempotency_key": hashlib.sha256(outreach_id.encode()).hexdigest(),
        "payload_sha256": service.sha(
            {
                "from": "info@bautica.test",
                "to": "iroda@minta-epito.test",
                "subject": "Szakmai egyeztetés",
                "body": "Részletes, hasznos szöveg a leiratkozási linkkel együtt.",
            }
        ),
        "status": status,
        "attempt_count": attempt_count,
        "max_attempts": 3,
    }
    values.update(kw)
    row = OutreachMessage(**values)
    db.add(row)
    db.commit()
    return row


def _signal_row(db, *, signal_id: str = "SIG-TEST-0001", **changes) -> GrowthSignal:
    data = _signal(**changes)
    row = GrowthSignal(
        signal_id=signal_id,
        run_id="GRUN-TEST",
        motor_key=data.motor_key,
        source_id=data.source_id,
        source_bucket=data.source_bucket,
        external_key=data.external_key,
        signal_type=data.signal_type,
        detected_at=data.detected_at,
        company_name=data.company_name,
        company_registration_id=data.company_registration_id,
        subject_type=data.subject_type,
        recipient_email=data.recipient_email,
        recipient_email_type=data.recipient_email_type,
        contact_basis=data.contact_basis,
        consent_evidence_id=data.consent_evidence_id,
        public_contact_url=data.public_contact_url,
        location=data.location,
        summary=data.summary,
        evidence_url=data.evidence_url,
        brand_id="bautica",
        score=80,
        urgency=data.urgency,
        confidence=data.confidence,
        dedupe_hash=hashlib.sha256(signal_id.encode()).hexdigest(),
        source_payload_hash=data.source_payload_hash,
        status="accepted",
    )
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------------------
# growth registry (real implementation)
# ---------------------------------------------------------------------------


def _registry_secret(tmp_path) -> str:
    secret = tmp_path / "bautica.json"
    secret.write_text(json.dumps({"host": "smtp.test", "port": 465}), encoding="utf-8")
    return secret.name


def _registry_raw(tmp_path, **overrides) -> dict:
    buckets = [
        "etdr",
        "public_request",
        "fitout_change",
        "property_development",
        "horeca",
        "contractor_capacity",
    ]
    distress = [
        "liquidation",
        "bankruptcy",
        "enforcement",
        "officer_change",
        "registered_office_change",
        "construction_dispute",
    ]
    sources = {
        f"construction-{b}": {"motor": "construction", "bucket": b, "enabled": False}
        for b in buckets
    }
    sources.update(
        {f"distress-{b}": {"motor": "distress", "bucket": b, "enabled": False} for b in distress}
    )
    sources["construction-etdr"]["enabled"] = True
    sources["construction-etdr"]["url"] = "https://source.test/etdr.json"
    sources["construction-etdr"]["kind"] = "json"
    sources["construction-etdr"]["policy_evidence"] = {
        "evidence_url": "https://source.test/policy",
        "checked_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "valid_until": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }
    raw = {
        "version": "registry-v1",
        "source": "test",
        "motors": {
            "construction": {
                "interval_minutes": 60,
                "max_raw_signals_per_run": 500,
                "daily_raw_review_target": 300,
            },
            "distress": {"interval_minutes": 60, "max_raw_signals_per_run": 500},
            "ivs": {"daily_at": "08:00", "max_raw_signals_per_run": 500},
        },
        "brands": {
            "bautica": {
                "sender_email": "info@bautica.test",
                "domain_key": "bautica-test",
                "secret_ref": _registry_secret(tmp_path),
                "templates": {"default": {"initial": {"subject": "S", "body": "B"}}},
            }
        },
        "sources": sources,
        "routing": {"residential_construction": "bautica"},
    }
    raw.update(overrides)
    return raw


@pytest.fixture
def real_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)
    return lambda raw: GrowthRegistry(raw)


def test_registry_valid_construction_and_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)
    registry = GrowthRegistry(_registry_raw(tmp_path))

    assert registry.version == "registry-v1"
    assert set(registry.motors) == {"construction", "distress", "ivs"}
    assert registry.brand_for("residential_construction") == "bautica"
    assert registry.brand_for("residential_construction", requested="bautica") == "bautica"
    sources = registry.sources_for("construction")
    assert [sid for sid, _ in sources] == ["construction-etdr"]
    registry.validate_signal_source(
        source_id="construction-etdr", motor_key="construction", source_bucket="etdr"
    )
    binding = registry.brand_binding("bautica")
    assert binding.secret == {"host": "smtp.test", "port": 465}
    state = registry.readiness()
    assert state["ready"] and state["enabled_sources"] == 1
    assert state["writes_unlocked"] in {True, False}


def test_registry_rejects_invalid_root_documents(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)
    with pytest.raises(GrowthRegistryError, match="version, motors, brands, sources and routing"):
        GrowthRegistry(_registry_raw(tmp_path, version=""))
    raw = _registry_raw(tmp_path)
    del raw["brands"]
    with pytest.raises(GrowthRegistryError, match="version, motors, brands, sources and routing"):
        GrowthRegistry(raw)
    with pytest.raises(GrowthRegistryError, match="Example registry"):
        GrowthRegistry(_registry_raw(tmp_path, source="example"))


def test_registry_rejects_motor_schedule_invariants(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)

    raw = _registry_raw(tmp_path)
    raw["motors"]["construction"]["daily_at"] = "09:00"  # both interval and daily
    with pytest.raises(GrowthRegistryError, match="Exactly one interval_minutes"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["construction"]["interval_minutes"] = 0
    with pytest.raises(GrowthRegistryError, match="Exactly one interval_minutes"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["construction"]["interval_minutes"] = -5
    with pytest.raises(GrowthRegistryError, match="Invalid motor schedule"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["ivs"]["daily_at"] = "25:00"
    with pytest.raises(GrowthRegistryError, match="Invalid motor schedule"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["construction"]["max_raw_signals_per_run"] = 0
    with pytest.raises(GrowthRegistryError, match="Invalid motor scan limit"):
        GrowthRegistry(raw)


def test_registry_rejects_fixed_motor_constants(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)

    raw = _registry_raw(tmp_path)
    raw["motors"]["construction"]["interval_minutes"] = 90
    with pytest.raises(GrowthRegistryError, match="Construction motor must run hourly"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["distress"]["interval_minutes"] = 90
    with pytest.raises(GrowthRegistryError, match="Distress motor must run hourly"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["ivs"]["daily_at"] = "07:00"
    with pytest.raises(GrowthRegistryError, match="IVS target motor must run daily at 08:00"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"]["construction"]["daily_raw_review_target"] = 100
    with pytest.raises(GrowthRegistryError, match="at least 300"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["motors"] = {"construction": raw["motors"]["construction"], "ivs": raw["motors"]["ivs"]}
    with pytest.raises(GrowthRegistryError, match="must be defined exactly"):
        GrowthRegistry(raw)


def test_registry_rejects_invalid_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)

    raw = _registry_raw(tmp_path)
    raw["sources"]["broken-source"] = "not-a-dict"
    with pytest.raises(GrowthRegistryError, match="Invalid source binding"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["sources"]["construction-etdr"] = {"motor": "construction"}  # no bucket
    with pytest.raises(GrowthRegistryError, match="Source motor/bucket is incomplete"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["sources"]["construction-etdr"]["url"] = "http://source.test/etdr.json"
    with pytest.raises(GrowthRegistryError, match="must use HTTPS"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["sources"]["construction-etdr"]["policy_evidence"] = {}
    with pytest.raises(GrowthRegistryError, match="evidence is required"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["sources"]["construction-etdr"]["policy_evidence"]["valid_until"] = (
        datetime.now(UTC) - timedelta(days=1)
    ).isoformat()
    with pytest.raises(GrowthRegistryError, match="evidence is required"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["sources"]["construction-etdr"]["kind"] = "csv"
    with pytest.raises(GrowthRegistryError, match="Unsupported enabled source kind"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    del raw["sources"]["construction-public_request"]
    del raw["sources"]["distress-liquidation"]
    with pytest.raises(GrowthRegistryError, match="construction source buckets"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    del raw["sources"]["distress-enforcement"]
    with pytest.raises(GrowthRegistryError, match="distress source buckets"):
        GrowthRegistry(raw)


def test_registry_rejects_invalid_brands_and_routing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)

    raw = _registry_raw(tmp_path)
    raw["brands"]["bautica"] = "bautica"
    with pytest.raises(GrowthRegistryError, match="Invalid brand"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["brands"]["bautica"]["sender_email"] = ""
    with pytest.raises(GrowthRegistryError, match="Brand sender binding is incomplete"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    del raw["brands"]["bautica"]["templates"]
    with pytest.raises(GrowthRegistryError, match="Brand outreach template missing"):
        GrowthRegistry(raw)

    raw = _registry_raw(tmp_path)
    raw["routing"]["residential_construction"] = "unknown-brand"
    with pytest.raises(GrowthRegistryError, match="Unknown routed brand"):
        GrowthRegistry(raw)


def test_registry_brand_for_and_source_validation_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)
    registry = GrowthRegistry(_registry_raw(tmp_path))

    with pytest.raises(GrowthRegistryError, match="conflicts with canonical signal routing"):
        registry.brand_for("residential_construction", requested="other-brand")
    with pytest.raises(GrowthRegistryError, match="No canonical brand route"):
        registry.brand_for("unrouted_type")
    with pytest.raises(GrowthRegistryError, match="not enabled"):
        registry.validate_signal_source(
            source_id="distress-liquidation", motor_key="distress", source_bucket="liquidation"
        )
    with pytest.raises(GrowthRegistryError, match="motor or bucket conflicts"):
        registry.validate_signal_source(
            source_id="construction-etdr", motor_key="distress", source_bucket="etdr"
        )
    with pytest.raises(GrowthRegistryError, match="Unknown brand"):
        registry.brand_binding("ghost-brand")


def test_registry_managed_secret_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(
            secret_dir=str(tmp_path), kill_switch_file=str(tmp_path / "gate")
        ),
    )
    secret = tmp_path / "ok.json"
    secret.write_text("{}", encoding="utf-8")

    with pytest.raises(GrowthRegistryError, match="escapes the managed secret directory"):
        growth_registry._managed_secret("../outside.json")
    with pytest.raises(GrowthRegistryError, match="Missing secret reference"):
        growth_registry._managed_secret("missing.json")

    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o644)
    with pytest.raises(GrowthRegistryError, match="permissions are too broad"):
        growth_registry._managed_secret("ok.json")
    monkeypatch.setattr(growth_registry.stat, "S_IMODE", lambda mode: 0o600)
    assert growth_registry._managed_secret("ok.json") == (tmp_path / "ok.json").resolve()


def test_registry_load_json_rejects_non_object(tmp_path, monkeypatch):
    path = tmp_path / "list.json"
    path.write_text("[1,2,3]", encoding="utf-8")
    with pytest.raises(GrowthRegistryError, match="not an object"):
        growth_registry._load_json(path)
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(GrowthRegistryError, match="Unreadable JSON reference"):
        growth_registry._load_json(path)


def test_registry_writes_unlocked_gate(monkeypatch, tmp_path):
    gate = tmp_path / "gate"
    monkeypatch.setattr(
        growth_registry,
        "settings",
        lambda: SimpleNamespace(kill_switch_file=str(gate)),
    )
    real_path = growth_registry.Path

    def fake_path(value):
        if str(value).startswith(str(tmp_path)):
            return real_path(str(value))
        return tmp_path / str(value).lstrip("/").replace("/", "_")

    monkeypatch.setattr(growth_registry, "Path", fake_path)
    monkeypatch.setenv("ENVIRONMENT", "test")

    kill_file = tmp_path / "app_runtime_growth-kill-switch"
    kill_file.write_text("KILLED", encoding="utf-8")
    assert growth_registry.writes_unlocked() is False
    kill_file.unlink()

    assert growth_registry.writes_unlocked() is False  # gate missing

    gate.write_text("ALLOW_APPROVED_WRITES", encoding="utf-8")
    assert growth_registry.writes_unlocked() is False  # not allowed in test env

    gate.write_text("ALLOW_STAGING_WRITES", encoding="utf-8")
    assert growth_registry.writes_unlocked() is True

    gate.unlink()
    gate.mkdir()
    assert growth_registry.writes_unlocked() is False  # read error (directory)


def test_registry_parse_helpers():
    assert growth_registry._parse_time(None) is None
    assert growth_registry._parse_time("not-a-date") is None
    naive = growth_registry._parse_time("2026-08-16T08:00:00")
    assert naive is not None and naive.tzinfo == UTC
    assert growth_registry._valid_clock("12:30") is True
    assert growth_registry._valid_clock("25:00") is False
    assert growth_registry._valid_clock("8") is False
    assert growth_registry._valid_clock("12:99") is False


# ---------------------------------------------------------------------------
# connectors (fake HTTP transport)
# ---------------------------------------------------------------------------


class FakeHTTPError(connectors.httpx.HTTPError):
    pass


class FakeSourceResponse:
    def __init__(self, *, content: bytes = b"", json_body=None, status: int = 200, text: str = ""):
        self._content = content
        self._json_body = json_body
        self.status_code = status
        self._text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise FakeHTTPError(f"HTTP {self.status_code}")

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        return self._text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


class FakeSourceClient:
    def __init__(self, response: FakeSourceResponse):
        self.response = response
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def source_transport(monkeypatch):
    def patch(response) -> FakeSourceClient:
        client = FakeSourceClient(response)
        monkeypatch.setattr(
            connectors.httpx,
            "Client",
            lambda **kwargs: client,
        )
        return client

    monkeypatch.setattr(connectors.httpx, "HTTPError", FakeHTTPError)
    return patch


def _json_source(**overrides) -> dict:
    source = {
        "url": "https://source.test/etdr.json",
        "kind": "json",
        "motor": "construction",
        "bucket": "etdr",
        "items_path": "data.items",
        "field_map": {
            "external_key": "key",
            "company_name": "company.name",
            "summary": "summary",
            "detected_at": "detected_at",
        },
        "defaults": {
            "signal_type": "residential_construction",
            "subject_type": "organization",
            "recipient_email": "iroda@minta-epito.test",
            "recipient_email_type": "role",
            "contact_basis": "public_business_contact",
            "public_contact_url": "https://minta-epito.test/kapcsolat",
            "confidence": 90,
            "urgency": 80,
            "company_registration_id": "01-09-999999",
            "evidence_url": "https://source.test/evidence/etdr",
        },
        "max_response_bytes": 5_000_000,
    }
    source.update(overrides)
    return source


def test_fetch_source_json_happy_path(source_transport):
    items = [
        {
            "key": "ETDR-2026-0100",
            "company": {"name": "Jelző Építő Kft."},
            "summary": "Új társasház építésének nyilvános bejelentése.",
            "detected_at": "2026-08-16T06:00:00+00:00",
        },
        {"key": "ETDR-2026-0101", "company": {"name": None}, "summary": "rövid"},
    ]
    client = source_transport(
        FakeSourceResponse(json_body={"data": {"items": items}})
    )
    batch = connectors.fetch_source("construction-etdr", _json_source(), limit=10)

    assert batch.raw_count == 2
    assert len(batch.signals) == 1
    assert batch.rejected_count == 1
    first = batch.signals[0]
    assert first.external_key == "ETDR-2026-0100"
    assert first.company_name == "Jelző Építő Kft."
    assert first.source_id == "construction-etdr" and first.motor_key == "construction"
    assert first.source_bucket == "etdr"
    assert first.detected_at == datetime(2026, 8, 16, 6, 0, tzinfo=UTC)
    assert len(first.source_payload_hash) == 64
    assert client.calls[0]["headers"]["User-Agent"].startswith("Imperial-Growth-Ops")


def test_fetch_source_json_uses_nested_paths_and_defaults(source_transport):
    client = source_transport(
        FakeSourceResponse(json_body=[{"key": "ETDR-2026-0200", "summary": "Építési jelzés."}])
    )
    source = _json_source(items_path="", field_map={"external_key": "key", "summary": "summary"})
    batch = connectors.fetch_source("construction-etdr", source, limit=5)
    assert batch.raw_count == 1
    assert batch.signals[0].detected_at <= datetime.now(UTC)  # missing -> now
    assert batch.signals[0].company_registration_id == "01-09-999999"


def test_fetch_source_json_failures(source_transport):
    # invalid JSON body
    source_transport(FakeSourceResponse(content=b"not json"))
    with pytest.raises(SourceError, match="invalid JSON"):
        connectors.fetch_source("construction-etdr", _json_source(), limit=10)
    # items path is not a list
    source_transport(FakeSourceResponse(json_body={"data": {"items": {}}}))
    with pytest.raises(SourceError, match="not a list"):
        connectors.fetch_source("construction-etdr", _json_source(), limit=10)
    # limit slices raw_count
    items = [{"key": f"K{i}", "summary": "Építési jelzés rövid szövege."} for i in range(5)]
    source_transport(FakeSourceResponse(json_body={"data": {"items": items}}))
    batch = connectors.fetch_source(
        "construction-etdr",
        _json_source(field_map={"external_key": "key", "summary": "summary"}),
        limit=2,
    )
    assert batch.raw_count == 2
    assert len(batch.signals) == 2


def test_fetch_source_rss_happy_path(source_transport):
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Építési hír</title>
        <link>https://source.test/hirek/1</link>
        <guid>HIR-1</guid>
        <pubDate>Sun, 16 Aug 2026 06:15:00 +0000</pubDate>
        <description>Részletes leírás a beruházásról.</description>
      </item>
    </channel></rss>""".encode("utf-8")
    client = source_transport(FakeSourceResponse(content=rss))
    source = {
        "url": "https://source.test/feed.xml",
        "kind": "rss",
        "motor": "construction",
        "bucket": "etdr",
        "defaults": {
            "signal_type": "residential_construction",
            "subject_type": "organization",
            "public_contact_url": "https://minta-epito.test/kapcsolat",
            "confidence": 70,
            "urgency": 60,
        },
    }
    batch = connectors.fetch_source("construction-etdr", source, limit=5)
    assert batch.raw_count == 1 and len(batch.signals) == 1
    signal = batch.signals[0]
    assert signal.external_key == "HIR-1"
    assert signal.evidence_url == "https://source.test/hirek/1"
    assert signal.detected_at == datetime(2026, 8, 16, 6, 15, tzinfo=UTC)
    assert signal.summary.startswith("Részletes leírás")


def test_fetch_source_rss_atom_and_skips_insecure_links(source_transport):
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom bejegyzés</title>
        <link href="https://source.test/atom/1"/>
        <id>ATOM-1</id>
        <updated>2026-08-16T07:00:00Z</updated>
        <summary>Atom összefoglaló.</summary>
      </entry>
      <entry>
        <title>Rossz link</title>
        <link href="http://insecure.test/x"/>
        <id>ATOM-2</id>
      </entry>
    </feed>""".encode("utf-8")
    source_transport(FakeSourceResponse(content=atom))
    source = {
        "url": "https://source.test/feed",
        "kind": "rss",
        "motor": "construction",
        "bucket": "etdr",
        "defaults": {"confidence": 50, "urgency": 50},
    }
    batch = connectors.fetch_source("construction-etdr", source, limit=5)
    assert batch.raw_count == 2 and len(batch.signals) == 1
    assert batch.signals[0].external_key == "https://source.test/atom/1"


def test_fetch_source_fail_closed_negatives(source_transport):
    source = _json_source(allowed_hosts=["other.test"])
    with pytest.raises(SourceError, match="not allowlisted"):
        connectors.fetch_source("construction-etdr", source, limit=5)

    source = _json_source(url="https://source.test/etdr.json", allowed_hosts=[])
    source_transport(FakeHTTPError("connection refused"))
    with pytest.raises(SourceError, match="Source request failed"):
        connectors.fetch_source("construction-etdr", source, limit=5)

    source_transport(FakeSourceResponse(content=b"x" * 100))
    source = _json_source(max_response_bytes=10)
    with pytest.raises(SourceError, match="exceeds the configured limit"):
        connectors.fetch_source("construction-etdr", source, limit=5)

    source_transport(FakeSourceResponse(json_body=[]))
    source = _json_source(kind="csv")
    with pytest.raises(SourceError, match="Unsupported source kind"):
        connectors.fetch_source("construction-etdr", source, limit=5)


def test_fetch_source_rss_invalid_xml(source_transport):
    source_transport(FakeSourceResponse(content=b"<broken"))
    source = {
        "url": "https://source.test/feed",
        "kind": "rss",
        "motor": "construction",
        "bucket": "etdr",
        "defaults": {},
    }
    with pytest.raises(SourceError, match="invalid RSS/Atom XML"):
        connectors.fetch_source("construction-etdr", source, limit=5)


def test_source_timestamp_invalid_raises(source_transport):
    source_transport(
        FakeSourceResponse(
            json_body=[{"key": "K-1", "summary": "Részletes szöveg.", "detected_at": "nope"}]
        )
    )
    with pytest.raises(SourceError, match="invalid timestamp"):
        connectors.fetch_source(
            "construction-etdr",
            _json_source(
                items_path="",
                field_map={"external_key": "key", "detected_at": "detected_at"},
            ),
            limit=5,
        )


# ---------------------------------------------------------------------------
# SMTP email adapter (fake smtplib)
# ---------------------------------------------------------------------------


class FakeSMTPServer:
    instances: list = []
    send_result: dict = {}
    login_error: Exception | None = None
    init_error: Exception | None = None
    send_error: Exception | None = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.calls: list = []
        FakeSMTPServer.instances.append(self)
        if FakeSMTPServer.init_error is not None:
            raise FakeSMTPServer.init_error

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if FakeSMTPServer.login_error is not None:
            raise FakeSMTPServer.login_error

    def send_message(self, message, from_addr, to_addrs):
        self.calls.append(("send_message", message, from_addr, to_addrs))
        if FakeSMTPServer.send_error is not None:
            raise FakeSMTPServer.send_error
        return FakeSMTPServer.send_result

    def ehlo(self):
        self.calls.append(("ehlo",))

    def starttls(self, context=None):
        self.calls.append(("starttls",))

    def quit(self):
        self.calls.append(("quit",))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.calls.append(("__exit__",))
        return False


class FakeSMTPAuthenticationError(RuntimeError):
    pass


class FakeSMTPException(Exception):
    pass


@pytest.fixture
def smtp_transport(monkeypatch):
    FakeSMTPServer.instances = []
    FakeSMTPServer.send_result = {}
    FakeSMTPServer.login_error = None
    FakeSMTPServer.init_error = None
    FakeSMTPServer.send_error = None
    fake_module = SimpleNamespace(
        SMTP_SSL=FakeSMTPServer,
        SMTP=FakeSMTPServer,
        SMTPAuthenticationError=FakeSMTPAuthenticationError,
        SMTPException=FakeSMTPException,
    )
    monkeypatch.setattr(email_mod, "smtplib", fake_module)
    return fake_module


def _smtp_binding(**secret_changes) -> BrandBinding:
    secret = {
        "host": "smtp.bautica.test",
        "port": 465,
        "username": "smtp-user",
        "password": synthetic_auth_value("bautica", "smtp"),
        "use_ssl": True,
    }
    secret.update(secret_changes)
    return BrandBinding(
        brand_id="bautica",
        sender_email="info@bautica.test",
        domain_key="bautica-test",
        secret=secret,
        config={"brand_name": "Bautica"},
    )


def test_smtp_preflight_fail_closed():
    incomplete = _smtp_binding()
    del incomplete.secret["port"]
    with pytest.raises(GrowthRegistryError, match="SMTP secret is incomplete"):
        SMTPEmailAdapter(incomplete).preflight()
    with pytest.raises(GrowthRegistryError, match="envelope sender conflicts"):
        SMTPEmailAdapter(_smtp_binding(envelope_from="other@bautica.test")).preflight()
    with pytest.raises(GrowthRegistryError, match="Encrypted SMTP transport is required"):
        SMTPEmailAdapter(_smtp_binding(use_ssl=False)).preflight()


def test_smtp_send_ssl_success(smtp_transport):
    adapter = SMTPEmailAdapter(_smtp_binding())
    receipt = adapter.send(
        to_email="iroda@minta-epito.test",
        subject="Szakmai egyeztetés",
        body_text="Tartalmas, hosszú üzenet a kapcsolatfelvételhez.",
        idempotency_key="a" * 64,
        reply_to="info@bautica.test",
    )
    server = FakeSMTPServer.instances[0]
    assert receipt.provider == "smtp" and receipt.accepted_recipient == "iroda@minta-epito.test"
    assert receipt.response_sha256 and receipt.provider_message_id.startswith("<")
    assert server.args[0] == "smtp.bautica.test" and server.args[1] == 465
    assert server.calls[0][0] == "login"
    message = server.calls[1][1]
    assert message["From"] == "info@bautica.test"
    assert message["To"] == "iroda@minta-epito.test"
    assert message["Reply-To"] == "info@bautica.test"
    assert message["X-Imperial-Idempotency-Key"] == "a" * 64
    assert server.calls[-1] == ("__exit__",)


def test_smtp_send_starttls_success(smtp_transport):
    adapter = SMTPEmailAdapter(_smtp_binding(use_ssl=False, starttls=True))
    receipt = adapter.send(
        to_email="iroda@minta-epito.test",
        subject="Szakmai egyeztetés",
        body_text="Tartalmas, hosszú üzenet a kapcsolatfelvételhez.",
        idempotency_key="b" * 64,
    )
    assert receipt.accepted_recipient == "iroda@minta-epito.test"
    server = FakeSMTPServer.instances[0]
    assert server.calls[:3] == [("ehlo",), ("starttls",), ("ehlo",)]


def test_smtp_send_authentication_failure(smtp_transport):
    FakeSMTPServer.login_error = FakeSMTPAuthenticationError("bad credentials")
    with pytest.raises(EmailDeliveryError) as exc_info:
        SMTPEmailAdapter(_smtp_binding()).send(
            to_email="x@test.hu",
            subject="Tárgy",
            body_text="Üzenet szövege hosszabban.",
            idempotency_key="c" * 64,
        )
    assert exc_info.value.retry_safe is False
    assert exc_info.value.authentication_failure is True


def test_smtp_send_connect_error_is_retry_safe(smtp_transport):
    FakeSMTPServer.init_error = OSError("connection refused")
    with pytest.raises(EmailDeliveryError) as exc_info:
        SMTPEmailAdapter(_smtp_binding()).send(
            to_email="x@test.hu",
            subject="Tárgy",
            body_text="Üzenet szövege hosszabban.",
            idempotency_key="d" * 64,
        )
    assert exc_info.value.retry_safe is True
    assert exc_info.value.authentication_failure is False


def test_smtp_send_refused_recipients(smtp_transport):
    FakeSMTPServer.send_result = {"iroda@minta-epito.test": (550, b"mailbox unavailable")}
    with pytest.raises(EmailDeliveryError, match="recipient_refused") as exc_info:
        SMTPEmailAdapter(_smtp_binding()).send(
            to_email="iroda@minta-epito.test",
            subject="Tárgy",
            body_text="Üzenet szövege hosszabban.",
            idempotency_key="e" * 64,
        )
    assert exc_info.value.retry_safe is False


def test_smtp_send_message_exception_is_ambiguous(smtp_transport):
    FakeSMTPServer.send_error = FakeSMTPException("connection dropped")
    with pytest.raises(EmailDeliveryError, match="ambiguous_delivery") as exc_info:
        SMTPEmailAdapter(_smtp_binding()).send(
            to_email="iroda@minta-epito.test",
            subject="Tárgy",
            body_text="Üzenet szövege hosszabban.",
            idempotency_key="f" * 64,
        )
    assert exc_info.value.retry_safe is False


# ---------------------------------------------------------------------------
# control state + ingest signal
# ---------------------------------------------------------------------------


def test_set_control_state_pause_and_errors(db):
    row = service.set_control_state(
        db, "construction", enabled=False, reason="Ad hoc átmeneti szünet", actor="test-admin"
    )
    assert row.enabled is False and row.changed_by == "test-admin"
    assert row.key == "motor:construction"
    updated = service.set_control_state(
        db, "construction", enabled=True, reason="Szünet feloldása megtörtént", actor="test-admin"
    )
    assert updated.enabled is True

    with pytest.raises(ValueError, match="Unknown growth motor"):
        service.set_control_state(db, "spam", enabled=True, reason="Hosszú indokló szöveg", actor="a")
    with pytest.raises(ValueError, match="detailed control-state reason"):
        service.set_control_state(db, "construction", enabled=True, reason="rövid", actor="a")


@pytest.mark.parametrize(
    ("changes", "expected_reason"),
    [
        (
            {"confidence": 10, "urgency": 10},
            "score_below_55",
        ),
        (
            {"detected_at": datetime.now(UTC) - timedelta(days=31)},
            "signal_older_than_30_days",
        ),
        (
            {"recipient_email": None, "recipient_email_type": "none"},
            "recipient_email_missing",
        ),
        (
            {
                "recipient_email": None,
                "recipient_email_type": "none",
                "contact_basis": "unknown",
            },
            "contact_basis_unknown",
        ),
        (
            {
                "company_name": None,
                "company_registration_id": None,
                "subject_type": "natural_person",
                "contact_basis": "public_business_contact",
            },
            "public_business_basis_requires_organization_role_inbox",
        ),
        (
            {"recipient_email_type": "named"},
            "named_or_unknown_mailbox_requires_consent_or_request",
        ),
    ],
)
def test_ingest_eligibility_rejections(db, growth_runtime, changes, expected_reason):
    result = service.ingest_signal(db, _signal(**changes))
    assert result.status == "rejected"
    assert expected_reason in result.reasons
    assert not db.scalars(select(OutreachMessage)).all()


def test_ingest_consent_basis_accepts_and_scores_higher(db, growth_runtime):
    result = service.ingest_signal(
        db,
        _signal(
            external_key="ETDR-2026-0300",
            company_registration_id="01-09-123456",
            contact_basis="explicit_request",
            consent_evidence_id="CONSENT-2026-001",
            public_contact_url=None,
        ),
    )
    assert result.status == "queued"
    assert result.score >= 55
    assert result.outreach_id


def test_ingest_verified_sender_fail_closed(db, growth_runtime):
    domain = db.scalar(
        select(MailSendingDomain).where(MailSendingDomain.domain_key == "bautica-test")
    )
    domain.dkim_status = "fail"
    db.commit()
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0400"))
    assert result.status == "blocked"
    assert any("SPF, DKIM and DMARC must all pass" in r for r in result.reasons)


def test_ingest_sending_domain_from_conflict_fail_closed(db, growth_runtime):
    domain = db.scalar(
        select(MailSendingDomain).where(MailSendingDomain.domain_key == "bautica-test")
    )
    domain.from_email = "other@bautica.test"
    db.commit()
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0401"))
    assert result.status == "blocked"
    assert any("conflicts with the brand registry" in r for r in result.reasons)


def test_ingest_missing_sending_domain_fail_closed(db, growth_runtime):
    db.delete(
        db.scalar(
            select(MailSendingDomain).where(MailSendingDomain.domain_key == "bautica-test")
        )
    )
    db.commit()
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0402"))
    assert result.status == "blocked"
    assert any("Verified sending domain binding is missing" in r for r in result.reasons)


def test_ingest_unconfigured_provider_fail_closed(db, growth_runtime):
    domain = db.scalar(
        select(MailSendingDomain).where(MailSendingDomain.domain_key == "bautica-test")
    )
    domain.provider = "provider_not_configured"
    db.commit()
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0403"))
    assert result.status == "blocked"
    assert any("Live mail provider is not configured" in r for r in result.reasons)


def test_ingest_template_missing_fail_closed(db, growth_runtime):
    growth_runtime.binding_config["templates"]["default"].pop("initial")
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0500"))
    assert result.status == "blocked"
    assert any("Outreach template missing" in r for r in result.reasons)


def test_ingest_unknown_template_token_fail_closed(db, growth_runtime):
    growth_runtime.binding_config["templates"]["default"]["initial"]["body"] = (
        "Ismeretlen token: {company_ceo_name}"
    )
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0501"))
    assert result.status == "blocked"
    assert any("Unknown outreach template token" in r for r in result.reasons)


def test_ingest_non_https_base_url_fail_closed(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: SimpleNamespace(
        base_url="http://intelligence.test.example",
        worker_id="growth-test-worker",
        lease_seconds=300,
        poll_seconds=30,
        enabled=True,
        timezone="Europe/Budapest",
    ))
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0502"))
    assert result.status == "blocked"
    assert any("HTTPS GROWTH_OPS_BASE_URL is required" in r for r in result.reasons)


def test_ingest_short_rendered_copy_fail_closed(db, growth_runtime):
    growth_runtime.binding_config["templates"]["default"]["initial"]["body"] = "Rövid."
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0503"))
    assert result.status == "blocked"
    assert any("useful copy and the unsubscribe URL" in r for r in result.reasons)


def test_ingest_brand_daily_rate_limit_fail_closed(db, growth_runtime):
    growth_runtime.binding_config["max_daily_messages"] = 2
    for index in range(2):
        _outreach_row(
            db,
            status="queued",
            outreach_id=f"OUT-RATE-{index}",
            signal_id=f"SIG-RATE-{index}",
            recipient_email=f"cimzett{index}@minta-epito.test",
            idempotency_key=f"rate-{index}".rjust(64, "0"),
        )
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0600"))
    assert result.status == "blocked"
    assert any("brand_daily_rate_limit" in r for r in result.reasons)


def test_ingest_recipient_brand_cooldown_fail_closed(db, growth_runtime):
    _outreach_row(
        db,
        status="sent",
        outreach_id="OUT-COOLDOWN-1",
        recipient_email="iroda@minta-epito.test",
        idempotency_key="cooldown-1".rjust(64, "0"),
        sequence_step=1,
        signal_id="SIG-COOLDOWN",
    )
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0601"))
    assert result.status == "blocked"
    assert any("recipient_brand_cooldown" in r for r in result.reasons)


def test_ingest_writes_locked_fail_closed(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "writes_unlocked", lambda: False)
    result = service.ingest_signal(db, _signal(external_key="ETDR-2026-0700"))
    assert result.status == "blocked"
    assert any("growth_writes_locked" in r for r in result.reasons)


def test_ingest_concurrent_idempotency_conflict(db, growth_runtime, monkeypatch):
    signal = _signal(external_key="ETDR-2026-0800")
    service.ingest_signal(db, signal)
    real_commit = db.commit

    def flaky_commit():
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(db, "commit", flaky_commit)
    with pytest.raises(ValueError, match="Concurrent growth-signal idempotency conflict"):
        service.ingest_signal(
            db,
            _signal(external_key="ETDR-2026-0801", company_registration_id="01-09-888888"),
        )
    monkeypatch.setattr(db, "commit", real_commit)


# ---------------------------------------------------------------------------
# motor runs, due motors, claim/dispatch pipeline
# ---------------------------------------------------------------------------


def test_run_motor_unknown_and_disabled(db, growth_runtime):
    with pytest.raises(KeyError):
        service.run_motor(db, "unknown-motor")

    db.add(GrowthControlState(key="motor:construction", enabled=False))
    db.commit()
    run = service.run_motor(db, "construction")
    assert run.status == "disabled" and run.completed_at is not None


def test_run_motor_full_cycle(db, growth_runtime, monkeypatch):
    growth_runtime.sources["construction-public_request"]["enabled"] = False

    def fake_fetch(source_id, source, *, limit):
        return SourceBatch(signals=[_signal(external_key="ETDR-2026-0900")], raw_count=1)

    monkeypatch.setattr(service, "fetch_source", fake_fetch)
    run = service.run_motor(db, "construction")
    assert run.status == "completed"
    assert run.attempted_sources == 1 and run.succeeded_sources == 1
    assert run.raw_signals == 1 and run.accepted_signals == 1 and run.queued_outreach == 1
    results = json.loads(run.source_results_json)
    assert results[0]["status"] == "ok" and results[0]["queued"] == 1
    assert db.scalar(select(GrowthSignal).where(GrowthSignal.run_id == run.run_id))


def test_run_motor_partial_and_failed(db, growth_runtime, monkeypatch):
    def flaky_fetch(source_id, source, *, limit):
        if source_id == "construction-etdr":
            raise SourceError("upstream unavailable")
        return SourceBatch(signals=[], raw_count=0)

    monkeypatch.setattr(service, "fetch_source", flaky_fetch)
    run = service.run_motor(db, "construction")
    assert run.status == "partial"
    assert run.succeeded_sources == 1 and run.attempted_sources == 2
    errors = json.loads(run.error_json)
    assert errors[0]["error_type"] == "SourceError"

    def always_fail(source_id, source, *, limit):
        raise SourceError("upstream unavailable")

    monkeypatch.setattr(service, "fetch_source", always_fail)
    run = service.run_motor(db, "construction")
    assert run.status == "failed" and run.succeeded_sources == 0


def test_run_motor_respects_scan_limit(db, growth_runtime, monkeypatch):
    growth_runtime.motors["construction"]["max_raw_signals_per_run"] = 100

    def oversized(source_id, source, *, limit):
        return SourceBatch(signals=[], raw_count=150)

    monkeypatch.setattr(service, "fetch_source", oversized)
    run = service.run_motor(db, "construction")
    assert run.status == "completed"
    assert run.attempted_sources == 1  # second source skipped, limit exhausted


def test_run_due_motors_and_interval_scheduling(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "fetch_source", lambda *a, **k: SourceBatch([], 0))
    runs = service.run_due_motors(db)
    assert len(runs) == 1 and runs[0].motor_key == "construction"

    again = service.run_due_motors(db)
    assert again == []  # interval not elapsed

    old = db.scalar(select(GrowthRun))
    old.started_at = datetime.now(UTC) - timedelta(hours=2)
    db.commit()
    third = service.run_due_motors(db)
    assert len(third) == 1

    monkeypatch.setattr(service, "settings", lambda: SimpleNamespace(
        base_url="https://intelligence.test.example",
        worker_id="w",
        lease_seconds=300,
        poll_seconds=30,
        enabled=False,
        timezone="Europe/Budapest",
    ))
    assert service.run_due_motors(db) == []


def test_motor_is_due_timezone_error(growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "settings", lambda: SimpleNamespace(
        base_url="https://intelligence.test.example",
        worker_id="w",
        lease_seconds=300,
        poll_seconds=30,
        enabled=True,
        timezone="Not/AZone",
    ))
    with pytest.raises(GrowthRegistryError, match="timezone is unavailable"):
        service._motor_is_due(datetime.now(UTC), None, {"daily_at": "08:00"})


def test_release_expired_claims_and_claim_outreach(db, growth_runtime):
    now = datetime.now(UTC)
    retryable = _outreach_row(
        db,
        status="claimed",
        attempt_count=1,
        lease_expires_at=now - timedelta(seconds=5),
        claimed_by="stale-worker",
        outreach_id="OUT-STALE-1",
        idempotency_key="stale-1".rjust(64, "0"),
    )
    dead = _outreach_row(
        db,
        status="claimed",
        attempt_count=3,
        max_attempts=3,
        lease_expires_at=now - timedelta(seconds=5),
        claimed_by="stale-worker",
        outreach_id="OUT-STALE-2",
        idempotency_key="stale-2".rjust(64, "0"),
        signal_id="SIG-STALE-2",
    )
    service._release_expired_claims(db)
    db.commit()
    db.refresh(retryable)
    db.refresh(dead)
    assert retryable.status == "queued" and retryable.claimed_by is None
    assert retryable.last_error == "worker lease expired"
    assert dead.status == "dead_letter"

    # the released row is eligible again and gets claimed
    claimed = service.claim_outreach(db)
    assert claimed is not None and claimed.outreach_id == retryable.outreach_id
    assert claimed.status == "claimed"
    assert claimed.claimed_by == "growth-test-worker"
    assert claimed.attempt_count == 2 and claimed.lease_expires_at is not None

    # no eligible row left -> None
    assert service.claim_outreach(db) is None

    queued = _outreach_row(
        db,
        status="queued",
        outreach_id="OUT-CLAIM-1",
        signal_id="SIG-CLAIM-1",
        idempotency_key="claim-1".rjust(64, "0"),
    )
    claimed = service.claim_outreach(db)
    assert claimed is not None and claimed.outreach_id == queued.outreach_id
    assert claimed.status == "claimed"
    assert claimed.attempt_count == 1 and claimed.lease_expires_at is not None


def test_dispatch_outreach_success(db, growth_runtime):
    receipt = service.ingest_signal(db, _signal(external_key="ETDR-2026-1000"))
    row = service.claim_outreach(db)
    assert row is not None
    result = service.dispatch_outreach(db, row)
    assert result.status == "sent"
    assert result.provider_message_id and result.sent_at is not None
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    assert signal.status == "contacted"
    assert receipt.outreach_id == row.outreach_id


def test_dispatch_outreach_missing_signal(db, growth_runtime):
    row = _outreach_row(db, signal_id="SIG-MISSING", outreach_id="OUT-MISSING-1",
                        idempotency_key="missing-1".rjust(64, "0"))
    result = service.dispatch_outreach(db, row)
    assert result.status == "queued"
    assert result.last_error == "GrowthRegistryError"
    assert result.available_at > datetime.now(UTC)  # backoff applied


def test_dispatch_outreach_writes_locked(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "writes_unlocked", lambda: False)
    _outreach_row(db, outreach_id="OUT-LOCKED-1", idempotency_key="locked-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    result = service.dispatch_outreach(db, row)
    assert result.status == "queued" and result.last_error == "GrowthRegistryError"


def test_dispatch_outreach_payload_hash_mismatch(db, growth_runtime, monkeypatch, tmp_path):
    kill_file = tmp_path / "growth-kill-switch"
    monkeypatch.setattr(service, "Path", lambda p: kill_file)
    _signal_row(db)
    _outreach_row(db, outreach_id="OUT-TAMPER-1", idempotency_key="tamper-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    row.body_text = row.body_text + " módosítva"
    db.commit()
    result = service.dispatch_outreach(db, row)
    assert result.status == "queued"
    assert result.last_error == "GrowthRegistryError"
    assert kill_file.exists()  # payload-hash mismatch trips the runtime kill switch


def test_dispatch_outreach_suppressed_recipient(db, growth_runtime):
    _signal_row(db)
    db.add(MailSuppression(email="iroda@minta-epito.test", reason="unsubscribe", active=True))
    db.commit()
    _outreach_row(db, outreach_id="OUT-SUPPRESS-1", idempotency_key="suppress-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    result = service.dispatch_outreach(db, row)
    assert result.status == "suppressed"
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    assert signal.status == "suppressed"


def test_dispatch_outreach_sender_changed_after_queue(db, growth_runtime):
    _signal_row(db)
    _outreach_row(db, outreach_id="OUT-SENDER-1", idempotency_key="sender-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    row.sender_email = "other@bautica.test"
    db.commit()
    result = service.dispatch_outreach(db, row)
    assert result.status == "queued"
    assert result.last_error == "GrowthRegistryError"


def test_dispatch_outreach_email_error_retry_safe(db, growth_runtime):
    FakeSMTPAdapter.fail = EmailDeliveryError("smtp_timeout", retry_safe=True)
    _signal_row(db)
    _outreach_row(db, outreach_id="OUT-ERR-1", idempotency_key="err-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    result = service.dispatch_outreach(db, row)
    assert result.status == "queued"
    assert result.available_at > datetime.now(UTC)


def test_dispatch_outreach_email_error_dead_letter(db, growth_runtime):
    FakeSMTPAdapter.fail = EmailDeliveryError("recipient_refused", retry_safe=False)
    _signal_row(db)
    _outreach_row(db, outreach_id="OUT-DL-1", idempotency_key="dl-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    result = service.dispatch_outreach(db, row)
    assert result.status == "dead_letter"


def test_dispatch_outreach_max_attempts_dead_letter(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "writes_unlocked", lambda: False)
    _outreach_row(
        db,
        outreach_id="OUT-MAX-1",
        idempotency_key="max-1".rjust(64, "0"),
        max_attempts=1,
    )
    row = service.claim_outreach(db)
    assert row.attempt_count == 1
    result = service.dispatch_outreach(db, row)
    assert result.status == "dead_letter"


def test_dispatch_outreach_auth_failure_trips_kill_switch(db, growth_runtime, monkeypatch, tmp_path):
    kill_file = tmp_path / "growth-kill-switch"
    monkeypatch.setattr(service, "Path", lambda p: kill_file)
    FakeSMTPAdapter.fail = EmailDeliveryError(
        "SMTPAuthenticationError", retry_safe=False, authentication_failure=True
    )
    _signal_row(db)
    _outreach_row(db, outreach_id="OUT-AUTH-1", idempotency_key="auth-1".rjust(64, "0"))
    row = service.claim_outreach(db)
    result = service.dispatch_outreach(db, row)
    assert result.status == "dead_letter"
    assert kill_file.exists()
    assert kill_file.read_text(encoding="utf-8").strip() == "KILLED"


def test_dispatch_batch_counts(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(service, "fetch_source", lambda *a, **k: SourceBatch([], 0))
    service.ingest_signal(
        db,
        _signal(
            external_key="ETDR-2026-1100",
            company_registration_id="01-09-111111",
            recipient_email="iroda1@minta-epito.test",
        ),
    )
    service.ingest_signal(
        db,
        _signal(
            external_key="ETDR-2026-1101",
            company_registration_id="01-09-222222",
            recipient_email="iroda2@minta-epito.test",
        ),
    )
    sent = service.dispatch_batch(db, limit=5)
    assert sent == 2
    assert service.dispatch_batch(db) == 0


# ---------------------------------------------------------------------------
# followups, provider events, unsubscribe, heartbeat, run_once, readiness
# ---------------------------------------------------------------------------


def test_schedule_followups_creates_next_step(db, growth_runtime):
    service.ingest_signal(db, _signal(external_key="ETDR-2026-1200"))
    row = service.claim_outreach(db)
    service.dispatch_outreach(db, row)
    row.sent_at = datetime.now(UTC) - timedelta(days=5)
    db.commit()

    created = service.schedule_followups(db)
    assert created == 1
    followup = db.scalar(
        select(OutreachMessage).where(OutreachMessage.sequence_step == 1)
    )
    assert followup is not None and followup.status == "queued"

    # already scheduled -> no duplicate
    assert service.schedule_followups(db) == 0


def test_schedule_followups_skips_responded_and_not_due(db, growth_runtime):
    service.ingest_signal(db, _signal(external_key="ETDR-2026-1300"))
    row = service.claim_outreach(db)
    service.dispatch_outreach(db, row)
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    signal.status = "responded"
    row.sent_at = datetime.now(UTC) - timedelta(days=5)
    db.commit()
    assert service.schedule_followups(db) == 0

    second = service.ingest_signal(
        db,
        _signal(
            external_key="ETDR-2026-1301",
            company_registration_id="01-09-333333",
            recipient_email="iroda2@minta-epito.test",
        ),
    )
    row2 = service.claim_outreach(db)
    assert row2 is not None
    service.dispatch_outreach(db, row2)
    row2.sent_at = datetime.now(UTC)  # not due yet
    db.commit()
    assert service.schedule_followups(db) == 0


def test_schedule_followups_requires_two_delays(db, growth_runtime):
    service.ingest_signal(db, _signal(external_key="ETDR-2026-1400"))
    row = service.claim_outreach(db)
    service.dispatch_outreach(db, row)
    row.sent_at = datetime.now(UTC) - timedelta(days=5)
    db.commit()
    growth_runtime.binding_config["followup_delays_days"] = [4]
    with pytest.raises(GrowthRegistryError, match="Exactly two follow-up delays"):
        service.schedule_followups(db)


def test_record_outreach_events(db, growth_runtime):
    service.ingest_signal(db, _signal(external_key="ETDR-2026-1500"))
    row = service.claim_outreach(db)
    outreach_id = row.outreach_id

    delivered = service.record_outreach_event(
        db, outreach_id, service.OutreachEventIn(event_type="delivered")
    )
    assert delivered.status == "delivered" and delivered.delivered_at is not None

    response = service.record_outreach_event(
        db, outreach_id, service.OutreachEventIn(event_type="response")
    )
    assert response.status == "responded"
    signal = db.scalar(select(GrowthSignal).where(GrowthSignal.signal_id == row.signal_id))
    assert signal.status == "responded"

    bounced = service.record_outreach_event(
        db, outreach_id, service.OutreachEventIn(event_type="bounce")
    )
    assert bounced.status == "bounced"
    suppression = db.scalar(
        select(MailSuppression).where(MailSuppression.email == row.recipient_email)
    )
    assert suppression is not None and suppression.active
    assert suppression.reason == "bounce"
    assert "growth_ops_provider_event" in suppression.source

    with pytest.raises(KeyError):
        service.record_outreach_event(db, "OUT-NOPE", service.OutreachEventIn(event_type="bounce"))


def test_unsubscribe_unknown_token_raises(db, growth_runtime):
    with pytest.raises(KeyError):
        service.unsubscribe(db, "no-such-token")


def test_heartbeat_create_and_update(db, growth_runtime):
    service.heartbeat(db, status="starting")
    row = db.get(GrowthWorkerHeartbeat, "growth-test-worker")
    assert row is not None and row.status == "starting"

    service.heartbeat(
        db,
        status="working",
        motor_key="construction",
        outreach_id="OUT-1",
        detail={"queued": 1},
    )
    db.refresh(row)
    assert row.status == "working"
    assert row.current_motor_key == "construction"
    assert json.loads(row.detail_json) == {"queued": 1}


def test_run_once_disabled(monkeypatch, db):
    FakeSMTPAdapter.fail = None
    monkeypatch.setattr(service, "settings", lambda: SimpleNamespace(
        base_url="https://intelligence.test.example",
        worker_id="growth-test-worker",
        lease_seconds=300,
        poll_seconds=30,
        enabled=False,
        timezone="Europe/Budapest",
    ))
    monkeypatch.setattr(service, "writes_unlocked", lambda: True)
    result = service.run_once(db)
    assert result == {"status": "disabled", "runs": 0, "followups": 0, "sent": 0}
    heartbeat = db.get(GrowthWorkerHeartbeat, "growth-test-worker")
    assert heartbeat is not None and heartbeat.status == "disabled"


def test_run_once_full_cycle(db, growth_runtime, monkeypatch):
    monkeypatch.setattr(
        service, "fetch_source", lambda *a, **k: SourceBatch([_signal()], raw_count=1)
    )
    result = service.run_once(db)
    assert result["status"] == "healthy"
    assert result["runs"] == 1 and result["followups"] == 0 and result["sent"] == 1
    heartbeat = db.get(GrowthWorkerHeartbeat, "growth-test-worker")
    assert heartbeat is not None and heartbeat.status == "healthy"
    assert json.loads(heartbeat.detail_json)["sent"] == 1


def test_readiness_ready(db, growth_runtime):
    db.add(GrowthWorkerHeartbeat(
        worker_id="growth-test-worker", status="healthy", heartbeat_at=datetime.now(UTC)
    ))
    db.commit()
    ready, detail = service.readiness(db)
    assert ready is True
    assert detail["database"] == "ok"
    assert detail["worker_heartbeat"] == "ok"
    assert detail["senders"][0]["ready"] is True


def test_readiness_stale_heartbeat_not_ready(db, growth_runtime):
    db.add(GrowthWorkerHeartbeat(
        worker_id="growth-test-worker",
        status="healthy",
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=30),
    ))
    db.commit()
    ready, detail = service.readiness(db)
    assert ready is False
    assert detail["worker_heartbeat"] == "stale_or_missing"


def test_readiness_registry_error_not_ready(db, growth_runtime, monkeypatch):
    def broken_load(cls):
        raise GrowthRegistryError("registry unavailable")

    monkeypatch.setattr(service.GrowthRegistry, "load", classmethod(broken_load))
    db.add(GrowthWorkerHeartbeat(
        worker_id="growth-test-worker", status="healthy", heartbeat_at=datetime.now(UTC)
    ))
    db.commit()
    ready, detail = service.readiness(db)
    assert ready is False
    assert detail["registry"]["ready"] is False
    assert detail["senders"] == []


def test_readiness_sender_not_ready(db, growth_runtime):
    db.delete(
        db.scalar(
            select(MailSendingDomain).where(MailSendingDomain.domain_key == "bautica-test")
        )
    )
    db.commit()
    db.add(GrowthWorkerHeartbeat(
        worker_id="growth-test-worker", status="healthy", heartbeat_at=datetime.now(UTC)
    ))
    db.commit()
    ready, detail = service.readiness(db)
    assert ready is False
    assert detail["senders"][0]["ready"] is False


def test_readiness_database_failure_fail_closed(db, growth_runtime, monkeypatch):
    real_execute = db.execute
    state = {"raised": False}

    def flaky_execute(*args, **kwargs):
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("database unavailable")
        return real_execute(*args, **kwargs)

    monkeypatch.setattr(db, "execute", flaky_execute)
    ready, detail = service.readiness(db)
    assert ready is False
    assert detail["database"] == "failed"


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------


@pytest.fixture
def growth_client(monkeypatch, client):
    from app.growth_ops import routes

    monkeypatch.setattr(
        routes,
        "platform_settings",
        SimpleNamespace(internal_job_token=_job_token()),
    )
    return client


def _auth_headers(token: str | None = None) -> dict:
    return {"X-Internal-Job-Token": token or _job_token()}


def test_growth_routes_require_internal_token(growth_client):
    response = growth_client.get("/api/internal/growth-ops/readiness")
    assert response.status_code == 401
    # Futásidőben képzett, determinisztikusan eltérő szintetikus hibás token a
    # közös factoryból; statikus credential-szerű literál nincs a diffben.
    invalid_auth = synthetic_auth_value("growth-ops", "wrong-token")
    assert invalid_auth != _job_token()
    response = growth_client.get(
        "/api/internal/growth-ops/readiness", headers=_auth_headers(invalid_auth)
    )
    assert response.status_code == 401


def test_growth_routes_readiness(growth_client, monkeypatch, db):
    from app.growth_ops import routes

    monkeypatch.setattr(routes, "readiness", lambda db_: (True, {"motors": ["construction"]}))
    response = growth_client.get(
        "/api/internal/growth-ops/readiness", headers=_auth_headers()
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

    monkeypatch.setattr(routes, "readiness", lambda db_: (False, {"reason": "stale"}))
    response = growth_client.get(
        "/api/internal/growth-ops/readiness", headers=_auth_headers()
    )
    assert response.status_code == 503


def test_growth_routes_signal_ingest(growth_client, monkeypatch, db):
    from app.growth_ops import routes

    payload = _signal().model_dump(mode="json")
    monkeypatch.setattr(
        routes,
        "ingest_signal",
        lambda db_, data: service.GrowthSignalReceipt(
            signal_id="SIG-ROUTE-1",
            status="queued",
            brand_id="bautica",
            score=88,
            idempotent=False,
            outreach_id="OUT-ROUTE-1",
        ),
    )
    response = growth_client.post(
        "/api/internal/growth-ops/signals", json=payload, headers=_auth_headers()
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    def registry_error(db_, data):
        raise GrowthRegistryError("source mismatch")

    monkeypatch.setattr(routes, "ingest_signal", registry_error)
    response = growth_client.post(
        "/api/internal/growth-ops/signals", json=payload, headers=_auth_headers()
    )
    assert response.status_code == 503

    def value_error(db_, data):
        raise ValueError("conflict")

    monkeypatch.setattr(routes, "ingest_signal", value_error)
    response = growth_client.post(
        "/api/internal/growth-ops/signals", json=payload, headers=_auth_headers()
    )
    assert response.status_code == 409


def test_growth_routes_motor_run(growth_client, monkeypatch, db):
    from app.growth_ops import routes

    now = datetime.now(UTC)
    run = GrowthRun(
        run_id="GRUN-ROUTE-1",
        motor_key="construction",
        scheduled_for=now,
        status="completed",
        attempted_sources=1,
        succeeded_sources=1,
        raw_signals=1,
        accepted_signals=1,
        queued_outreach=1,
        started_at=now,
        completed_at=now,
    )
    monkeypatch.setattr(routes, "run_motor", lambda db_, motor_key: run)
    response = growth_client.post(
        "/api/internal/growth-ops/motors/construction/run", headers=_auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "GRUN-ROUTE-1" and body["status"] == "completed"

    def unknown_motor(db_, motor_key):
        raise KeyError(motor_key)

    monkeypatch.setattr(routes, "run_motor", unknown_motor)
    response = growth_client.post(
        "/api/internal/growth-ops/motors/construction/run", headers=_auth_headers()
    )
    assert response.status_code == 404

    def registry_failure(db_, motor_key):
        raise GrowthRegistryError("registry unavailable")

    monkeypatch.setattr(routes, "run_motor", registry_failure)
    response = growth_client.post(
        "/api/internal/growth-ops/motors/construction/run", headers=_auth_headers()
    )
    assert response.status_code == 503


def test_growth_routes_motor_control(growth_client, monkeypatch, db):
    from app.growth_ops import routes

    row = GrowthControlState(
        key="motor:construction",
        enabled=False,
        reason="Ad hoc átmeneti szünet",
        changed_by="growth-admin",
        changed_at=datetime.now(UTC),
    )
    monkeypatch.setattr(routes, "set_control_state", lambda *a, **k: row)
    response = growth_client.post(
        "/api/internal/growth-ops/motors/construction/control",
        json={"enabled": False, "reason": "Ad hoc átmeneti szünet"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    def bad_control(*args, **kwargs):
        raise ValueError("Unknown growth motor")

    monkeypatch.setattr(routes, "set_control_state", bad_control)
    response = growth_client.post(
        "/api/internal/growth-ops/motors/construction/control",
        json={"enabled": False, "reason": "Ad hoc átmeneti szünet"},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


def test_growth_routes_outreach_event(growth_client, monkeypatch, db):
    from app.growth_ops import routes

    now = datetime.now(UTC)
    row = OutreachMessage(
        outreach_id="OUT-ROUTE-1",
        signal_id="SIG-ROUTE-1",
        brand_id="bautica",
        status="delivered",
        sequence_step=0,
        attempt_count=1,
        sent_at=now,
        delivered_at=now,
        response_at=None,
    )
    monkeypatch.setattr(routes, "record_outreach_event", lambda *a, **k: row)
    response = growth_client.post(
        "/api/internal/growth-ops/outreach/OUT-ROUTE-1/events",
        json={"event_type": "delivered"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "delivered"

    def unknown_outreach(*args, **kwargs):
        raise KeyError("OUT-NOPE")

    monkeypatch.setattr(routes, "record_outreach_event", unknown_outreach)
    response = growth_client.post(
        "/api/internal/growth-ops/outreach/OUT-NOPE/events",
        json={"event_type": "bounce"},
        headers=_auth_headers(),
    )
    assert response.status_code == 404


def test_growth_routes_unsubscribe(growth_client, monkeypatch, db):
    from app.growth_ops import routes

    monkeypatch.setattr(routes, "unsubscribe", lambda db_, token: None)
    response = growth_client.get("/growth/unsubscribe/valid-token")
    assert response.status_code == 200
    assert "leiratkozás" in response.text

    def unknown_token(db_, token):
        raise KeyError(token)

    monkeypatch.setattr(routes, "unsubscribe", unknown_token)
    response = growth_client.get("/growth/unsubscribe/unknown-token")
    assert response.status_code == 404
