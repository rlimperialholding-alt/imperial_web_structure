from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from app import seed
from app.growth_ops.processing import _approved_brand_facts
from app.growth_ops.revenue_policy import build_brand_source_intent
from app.models import CopySourceRecord


def test_manifest_contains_read_back_documents_and_supported_brand_specific_steps():
    manifest = json.loads(
        (Path(seed.__file__).parent / "content_factory_source_manifest.json").read_text("utf8")
    )
    assert manifest["manifest_version"] == "2026-09-07.v1"
    for brand in manifest["brands"]:
        for source in brand["sources"]:
            payload = source["payload"]
            assert payload["source_refs"] == [source["source_url"]]
            proof = payload["source_evidence"][0]
            assert proof["drive_file_id"] in source["source_url"]
            assert len(proof["content_sha256"]) == 64
            assert proof["exact_excerpts"]
            assert source["supersedes_versions"] == ["2026-09-06.v1"]


def test_seed_supersedes_only_explicit_versions_and_is_idempotent(db):
    key = "property360-brand-fact-project-coordination"
    payload = json.dumps({"statement": "Old source"})
    for version in ("2026-09-06.v1", "operator-other-source-v1"):
        db.add(CopySourceRecord(
            source_key=key, brand_id="Property360", source_type="brand_fact",
            version=version, priority=20, status="approved", approved=True,
            source_url="https://docs.google.com/document/d/test-source/edit",
            content_hash=hashlib.sha256(payload.encode()).hexdigest(), payload_json=payload,
        ))
    db.flush()
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    rows = list(db.scalars(select(CopySourceRecord).where(CopySourceRecord.source_key == key)))
    by_version = {row.version: row for row in rows}
    assert len(rows) == 3
    assert by_version["2026-09-06.v1"].status == "superseded"
    assert by_version["2026-09-06.v1"].approved is False
    assert by_version["operator-other-source-v1"].approved is True
    assert by_version["2026-09-07.v1"].approved is True


def test_seeded_sources_make_three_distinct_reviewable_brand_inputs(db):
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    expected = {
        "Property360": "Kérek telek–ház elővizsgálatot.",
        "RED Property": "Kérem az árat.",
        "Venture Studio": "Kérek befektetői meghívást.",
    }
    for brand, next_step in expected.items():
        facts = _approved_brand_facts(db, brand, current=datetime(2026, 9, 7, tzinfo=UTC))
        intent = build_brand_source_intent(brand, facts)
        assert intent["brand_id"] == brand
        assert intent["next_step"] == next_step
        assert intent["publication_allowed"] is False
        assert intent["send_allowed"] is False
        assert all(fact["payload"]["source_evidence"] for fact in facts)
