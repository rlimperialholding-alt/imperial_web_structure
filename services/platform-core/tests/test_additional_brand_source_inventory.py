from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from app import seed
from app.growth_ops.processing import _approved_brand_facts
from app.growth_ops.revenue_policy import build_brand_source_intent, evaluate_revenue_intent
from app.models import CopySourceRecord

NOW = datetime(2026, 9, 7, tzinfo=UTC)
EXPECTED_STEPS = {
    "Bautica": "Kérek műszaki kalkulációt.",
    "BauFreund": "Kérek egy őszinte költségbecslést.",
    "Prefab": "Kérek tételes mérnöki ajánlatot.",
    "TimberHaus": "Kérek szerkezeti ajánlatot.",
    "Danish Fabrik": "Kérek árajánlatot",
    "Imperial": "Költségbecslést kérek.",
}


@pytest.mark.parametrize("brand_id,next_step", EXPECTED_STEPS.items())
def test_additional_sources_produce_usable_distinct_customer_inputs(db, brand_id, next_step):
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    facts = _approved_brand_facts(db, brand_id, current=NOW)
    assert len(facts) == 1
    fact = facts[0]
    assert fact["brand_id"] == brand_id
    proof = fact["payload"]["source_evidence"][0]
    assert proof["drive_file_id"] in fact["source_url"]
    assert proof["source_modified_time"] < proof["readback_at"]
    assert len(proof["content_sha256"]) == 64
    assert proof["exact_excerpts"]

    intent = build_brand_source_intent(brand_id, facts)
    assert evaluate_revenue_intent(intent, brand_id=brand_id)["eligible"]
    assert intent["next_step"] == next_step
    assert intent["input_type"] == "approved_brand_customer_problem"
    assert intent["radar_topic_id"] is None
    assert intent["source_refs"] == [fact["source_url"]]
    assert intent["buyer_problem"] == fact["payload"]["buyer_problems"][0]
    assert intent["sales_goal"] == fact["payload"]["sales_goal"]
    assert intent["publication_allowed"] is False
    assert intent["send_allowed"] is False

    first_id = db.scalar(select(CopySourceRecord.id).where(
        CopySourceRecord.source_key == fact["source_key"],
        CopySourceRecord.version == fact["version"],
    ))
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    repeated_ids = list(db.scalars(select(CopySourceRecord.id).where(
        CopySourceRecord.source_key == fact["source_key"],
        CopySourceRecord.version == fact["version"],
    )))
    assert repeated_ids == [first_id]


def test_additional_inventory_preserves_original_five_sources_exactly():
    manifest = json.loads(
        (Path(seed.__file__).parent / "content_factory_source_manifest.json").read_text("utf8")
    )
    originals = [row for row in manifest["brands"] if row["brand_id"] in {
        "Property360", "RED Property", "Venture Studio",
    }]
    content = json.dumps(originals, ensure_ascii=False, sort_keys=True).encode("utf8")
    assert hashlib.sha256(content).hexdigest() == (
        "089d68d61729c69584ebd1d0a9b5803d5040d059c2240dc377ebe945fe5f09c8"
    )
    additions = [row for row in manifest["brands"] if row["brand_id"] in EXPECTED_STEPS]
    assert len(additions) == 6
    assert all(source["supersedes_versions"] == []
               for row in additions for source in row["sources"])


def test_static_sources_do_not_renew_expired_prices_or_replace_operator_records(db):
    payload_json = json.dumps({"statement": "An expired historical price."})
    expired = CopySourceRecord(
        source_key="prefab-existing-expired-price", brand_id="Prefab", source_type="offer",
        version="2026-08", priority=1, status="approved", approved=True,
        valid_until=datetime(2026, 8, 31, tzinfo=UTC),
        source_url="https://example.org/historical-prefab-price",
        payload_json=payload_json,
        content_hash=hashlib.sha256(payload_json.encode()).hexdigest(),
    )
    package_payload = json.dumps({"package_hash": "existing-package-only"})
    old_imperial = CopySourceRecord(
        source_key="imperial-operator-package", brand_id="Imperial", source_type="brand_fact",
        version="operator-v1", priority=1, status="approved", approved=True,
        source_url="https://example.org/imperial-package",
        payload_json=package_payload,
        content_hash=hashlib.sha256(package_payload.encode()).hexdigest(),
    )
    db.add_all([expired, old_imperial])
    db.flush()
    previous_ids = (expired.id, old_imperial.id)

    seed.seed_content_factory_source_inventory(db)
    db.flush()
    db.refresh(expired)
    db.refresh(old_imperial)
    assert (expired.id, old_imperial.id) == previous_ids
    assert expired.valid_until.date().isoformat() == "2026-08-31"
    assert expired.payload_json == payload_json
    assert expired.approved is True and expired.status == "approved"
    assert old_imperial.payload_json == package_payload
    assert old_imperial.approved is True and old_imperial.status == "approved"
    prefab_facts = _approved_brand_facts(db, "Prefab", current=NOW)
    imperial_facts = _approved_brand_facts(db, "Imperial", current=NOW)
    assert [row["source_key"] for row in prefab_facts] == [
        "prefab-brand-fact-massive-prefabrication",
    ]
    assert [row["source_key"] for row in imperial_facts] == [
        "imperial-brand-fact-design-and-construction",
    ]


def test_new_inventory_contains_no_unproved_numeric_or_independence_promises(db):
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    for brand_id in EXPECTED_STEPS:
        facts = _approved_brand_facts(db, brand_id, current=NOW)
        intent = build_brand_source_intent(brand_id, facts)
        output_claims = " ".join([
            facts[0]["payload"]["statement"], intent["next_step"],
            intent["buyer_problem"], intent["sales_goal"],
        ]).casefold()
        assert not any(char.isdigit() for char in output_claims)
        assert not any(term in output_claims for term in (
            "garantált", "kockázatmentes", "független", "fix ár", "fix határidő", "aaa",
        ))
        assert facts[0]["payload"]["claim_limits"]
