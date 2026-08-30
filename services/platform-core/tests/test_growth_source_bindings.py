from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from app.growth_ops.registry import (
    GrowthRegistry,
    GrowthRegistryError,
    _official_source_binding_sha256,
)


def _authority(tmp_path, monkeypatch) -> tuple[str, str]:
    path = tmp_path / "real-estate-sources.json"
    payload = {
        "registry_id": "IMPERIAL_REAL_ESTATE_DISCOVERY_SOURCES_HU_V1",
        "version": 1,
        "status": ["OWNER_APPROVED", "CANONICAL"],
        "discovery_policy": {
            "allow_unlisted_public_sources": True,
            "include_search_discovered_sources": True,
            "runtime_live_check_required": True,
            "current_listing_or_current_office_page_required": True,
            "architect_office_sources_may_be_discovered_outside_real_estate_portals": True
        },
        "dynamic_discovery": {
            "enabled": True,
            "stable_source_id_format": "DYNAMIC_<COUNTRY>_<NORMALIZED_ROOT_DOMAIN>",
            "same_send_gates_as_seed_sources": True,
            "new_source_must_be_logged_with_root_domain_and_evidence_url": True,
            "new_source_does_not_require_registry_file_edit_before_use": True,
            "source_reputation_or_identity_uncertainty": "NO_SEND",
        },
        "send_gates": {
            "allowed_recipient_types": [
                "architect_office",
                "land_owner",
                "real_estate_agent",
            ]
        },
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    monkeypatch.setenv("REAL_ESTATE_SOURCE_REGISTRY_FILE", str(path))
    return str(path), hashlib.sha256(path.read_bytes()).hexdigest()


def _raw(authority_sha256: str) -> dict:
    now = datetime.now(UTC)
    sources = {
        "construction_etdr": {"enabled": False, "motor": "construction", "bucket": "etdr"},
        "construction_public_request": {
            "enabled": False,
            "motor": "construction",
            "bucket": "public_request",
        },
        "construction_fitout_change": {
            "enabled": False,
            "motor": "construction",
            "bucket": "fitout_change",
        },
        "construction_property_development": {
            "enabled": False,
            "motor": "construction",
            "bucket": "property_development",
        },
        "construction_horeca": {
            "enabled": False,
            "motor": "construction",
            "bucket": "horeca",
        },
        "construction_contractor_capacity": {
            "enabled": False,
            "motor": "construction",
            "bucket": "contractor_capacity",
        },
        "distress_liquidation": {
            "enabled": False,
            "motor": "distress",
            "bucket": "liquidation",
        },
        "distress_bankruptcy": {
            "enabled": False,
            "motor": "distress",
            "bucket": "bankruptcy",
        },
        "distress_enforcement": {
            "enabled": False,
            "motor": "distress",
            "bucket": "enforcement",
        },
        "distress_officer_change": {
            "enabled": False,
            "motor": "distress",
            "bucket": "officer_change",
        },
        "distress_registered_office_change": {
            "enabled": False,
            "motor": "distress",
            "bucket": "registered_office_change",
        },
        "distress_construction_dispute": {
            "enabled": False,
            "motor": "distress",
            "bucket": "construction_dispute",
        },
        "DYNAMIC_HU_ARCHIKON_HU": {
            "enabled": True,
            "motor": "construction",
            "bucket": "architect_office",
            "kind": "official_company_html",
            "fetch_mode": "ingest_only",
            "url": "https://archikon.hu/",
            "allowed_evidence_urls": ["https://archikon.hu/"],
            "context_evidence_url": "https://archikon.hu/",
            "public_contact_url": "https://archikon.hu/",
            "max_evidence_age_seconds": 3600,
            "recipient_binding": {
                "recipient_type": "architect_office",
                "recipient_email": "office@archikon.hu",
                "recipient_email_type": "role",
                "contact_basis": "public_business_contact",
                "primary_language": "hu",
                "organization_names": ["Archikon"],
                "recipient_names": ["Archikon"],
            },
            "policy_evidence": {
                "evidence_url": "https://archikon.hu/",
                "final_url": "https://archikon.hu/",
                "checked_at": (now - timedelta(minutes=1)).isoformat(),
                "valid_until": (now + timedelta(days=1)).isoformat(),
                "http_status": 200,
                "content_type": "text/html; charset=UTF-8",
                "content_sha256": "a" * 64,
            },
            "authority": {
                "registry_id": "IMPERIAL_REAL_ESTATE_DISCOVERY_SOURCES_HU_V1",
                "version": 1,
                "sha256": authority_sha256,
                "owner_instruction_ref": (
                    "imperial-kanonikus-els-megkeres-s-napi-canary/2026-08-27"
                ),
            },
        },
    }
    sources["DYNAMIC_HU_ARCHIKON_HU"]["binding_sha256"] = (
        _official_source_binding_sha256(
            "DYNAMIC_HU_ARCHIKON_HU",
            sources["DYNAMIC_HU_ARCHIKON_HU"],
        )
    )
    return {
        "version": "unit-test-v1",
        "source": "owner-authorized-unit-test",
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
            "imperial": {
                "sender_email": "info@imperialholding.hu",
                "domain_key": "imperial_gmail_api",
                "secret_ref": "unused-test-secret.json",
            }
        },
        "sources": sources,
        "routing": {"architect_office": "imperial"},
    }


@pytest.fixture
def official_registry(tmp_path, monkeypatch):
    authority_path, authority_sha256 = _authority(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.growth_ops.registry._managed_secret",
        lambda _reference: tmp_path / "unused-test-secret.json",
    )
    return GrowthRegistry(_raw(authority_sha256)), authority_path, authority_sha256


def _binding_args(binding_hash: str, **changes) -> dict:
    payload = {
        "source_id": "DYNAMIC_HU_ARCHIKON_HU",
        "motor_key": "construction",
        "source_bucket": "architect_office",
        "recipient_type": "architect_office",
        "recipient_email": "office@archikon.hu",
        "recipient_email_type": "role",
        "contact_basis": "public_business_contact",
        "recipient_name": "Archikon",
        "company_name": "Archikon",
        "recipient_organization_name": None,
        "evidence_url": "https://archikon.hu/",
        "public_contact_url": "https://archikon.hu/",
        "source_payload_hash": binding_hash,
        "detected_at": datetime.now(UTC),
    }
    payload.update(changes)
    return payload


def test_ingest_only_official_company_source_is_not_scheduled(official_registry):
    registry, _, _ = official_registry
    assert registry.sources_for("construction") == []
    binding_hash = registry.sources["DYNAMIC_HU_ARCHIKON_HU"]["binding_sha256"]
    registry.validate_signal_source(**_binding_args(binding_hash))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipient_type", "referral_partner"),
        ("recipient_email", "other@archikon.hu"),
        ("recipient_email_type", "named"),
        ("contact_basis", "unknown"),
        ("recipient_name", "Another office"),
        ("company_name", "Another office"),
        ("evidence_url", "https://archikon.hu/projects"),
        ("public_contact_url", "https://sub.archikon.hu/"),
        ("source_payload_hash", "b" * 64),
        ("detected_at", datetime.now(UTC) - timedelta(hours=2)),
    ],
)
def test_official_company_signal_binding_is_exact_and_fresh(
    official_registry, field, value
):
    registry, _, _ = official_registry
    binding_hash = registry.sources["DYNAMIC_HU_ARCHIKON_HU"]["binding_sha256"]
    with pytest.raises(GrowthRegistryError):
        registry.validate_signal_source(
            **_binding_args(binding_hash, **{field: value})
        )


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (
            ("sources", "DYNAMIC_HU_ARCHIKON_HU", "fetch_mode"),
            "scheduled",
            "ingest-only",
        ),
        (
            ("sources", "DYNAMIC_HU_ARCHIKON_HU", "bucket"),
            "referral_partner",
            "restricted",
        ),
        (
            ("sources", "DYNAMIC_HU_ARCHIKON_HU", "url"),
            "https://unknown.example/",
            "root domain",
        ),
        (
            ("sources", "DYNAMIC_HU_ARCHIKON_HU", "allowed_evidence_urls"),
            ["http://archikon.hu/"],
            "exact evidence",
        ),
        (
            (
                "sources",
                "DYNAMIC_HU_ARCHIKON_HU",
                "recipient_binding",
                "recipient_type",
            ),
            "referral_partner",
            "recipient binding",
        ),
        (
            (
                "sources",
                "DYNAMIC_HU_ARCHIKON_HU",
                "policy_evidence",
                "content_sha256",
            ),
            "bad",
            "live evidence",
        ),
        (
            ("sources", "DYNAMIC_HU_ARCHIKON_HU", "authority", "sha256"),
            "0" * 64,
            "canonical policy",
        ),
    ],
)
def test_invalid_official_company_registry_binding_fails_closed(
    tmp_path, monkeypatch, path, value, message
):
    _, authority_sha256 = _authority(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.growth_ops.registry._managed_secret",
        lambda _reference: tmp_path / "unused-test-secret.json",
    )
    raw = deepcopy(_raw(authority_sha256))
    target = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(GrowthRegistryError, match=message):
        GrowthRegistry(raw)


def test_authority_artifact_bytes_are_hash_bound(official_registry):
    registry, authority_path, _ = official_registry
    with open(authority_path, "a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(GrowthRegistryError, match="canonical policy"):
        GrowthRegistry(deepcopy(registry.raw))
