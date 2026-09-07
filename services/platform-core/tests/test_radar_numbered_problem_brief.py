"""Runtime briefs preserve original quantities without loosening claim checks."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.growth_ops import catalog, processing, revenue_policy


NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)
FEED = "https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25"
FIXTURE = Path(__file__).parent / "fixtures/forum_real_sources/reddit_lakokozosseg.atom"


def _runtime_case(db):
    _, candidates = catalog._page_evidence(FIXTURE.read_text(encoding="utf-8"), base_url=FEED, limit=24000)
    item = next(value for value in candidates if "/1w8rs4c/" in value["url"])
    original = item["label"].partition("[SOURCE_PAGE_EVIDENCE]")[0].strip()
    metadata = processing._source_page_metadata_from_label(item["label"])
    freshness = processing._question_freshness(
        {**metadata, "source_url": item["url"], "question": original},
        evidence_text=item["label"], observed_at=NOW, require_source_date_proof=True,
    )
    assert freshness["published_at"] is not None
    topic = {
        "topic_id": "QRT-PROPOSAL-REAL-MUNKADIJAK", "brand_id": "Property360",
        "question": original, "source_url": item["url"], **freshness,
    }
    intent = revenue_policy.build_revenue_intent(
        topic, approved_brand_facts=processing._approved_brand_facts(db, "Property360", current=NOW),
        sales_goal="Konkrét felújítási feladatok és költségtartalom egyeztetése.",
        next_step="Kérek telek–ház elővizsgálatot.", now=NOW,
    )
    proposed = intent
    public_problem = intent["buyer_problem"]
    statement = proposed["approved_brand_facts"][0]["payload"]["statement"]
    package = {
        "brand_id": "Property360", "title": "Padlózás és festés: mit tartalmaz a munkadíj?",
        "body": public_problem + " " + statement + "\n\n"
        "Az összehasonlítást a feladatok leírásával kezdd. A padló lerakása előtt tisztázd, "
        "hogy az aljzat előkészítése és a szegélyezés része-e az ajánlatnak. A festésnél "
        "a fal állapota és az előkészítés külön egyeztetendő. Kérj azonos feladatlistára "
        "tételes ajánlatokat, és külön jelöld az anyagokat, a munkadíjat és az elszállítást. "
        "Így láthatóvá válik, melyik ajánlat mire vonatkozik, és milyen további információ "
        "szükséges az összehasonlításhoz. A munkafolyamatot és a fizetés feltételeit "
        "a választott szakemberrel írásban is egyeztesd.",
        "facebook_post": "Padlózás és festés előtt tisztázd, mit tartalmaz a munkadíj. "
        "Az aljzat előkészítése, a szegélyezés és a fal javítása külön egyeztetendő. "
        "Azonos feladatlistára kérj tételes ajánlatokat. #felújítás #padlózás #festés",
        "cta": {"label": proposed["next_step"], "intent": "lead"},
        "source_urls": proposed["source_refs"], "revenue_intent": proposed,
    }
    return original, proposed, package


def test_runtime_keeps_actual_problem_source_and_existing_validators_accept_copy(db):
    original, proposed, package = _runtime_case(db)
    assert "20 m2-es" in original
    assert "megadott méretű szobában laminált padló lerakása" in proposed["buyer_problem"]
    assert not re.search(r"\d", proposed["buyer_problem"])
    evidence = proposed["source_problem_evidence"]
    assert evidence["original_problem"] == original
    assert evidence["published_at_raw"] == "2026-09-06T09:45:34+00:00"
    assert evidence["native_id"] == "post:1w8rs4c"
    assert evidence["source_identity"] == revenue_policy._problem_source_identity(evidence["source_url"] + "?utm_source=replay")[0]
    assert evidence["original_text_sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
    assert processing._revenue_package_errors(package, proposed) == []
    assert processing._content_repair_errors(package, {}) == []
    assert processing._required_copy_spans(proposed)[0] == proposed["buyer_problem"]


def test_raw_numeric_problem_currently_conflicts_but_invented_price_stays_disallowed(db):
    original, proposed, package = _runtime_case(db)
    raw_intent = dict(proposed, buyer_problem=original)
    raw_package = dict(package, body=package["body"].replace(proposed["buyer_problem"], original), revenue_intent=raw_intent)
    assert processing._revenue_package_errors(raw_package, raw_intent) == []
    assert "unverified_numeric_claim" in processing._deterministic_publication_errors(raw_package, {})
    changed = deepcopy(package)
    changed["body"] += " A kivitelezés ára 900000 Ft."
    changed["revenue_intent"]["source_problem_evidence"]["numeric_claims_approved"] = ["900000 Ft"]
    assert "unverified_numeric_claim" in processing._deterministic_publication_errors(changed, {})


def test_existing_hmac_still_binds_public_copy_and_source_urls(db, monkeypatch):
    _, _, package = _runtime_case(db)
    monkeypatch.setattr(processing, "_quality_release_secret", lambda: b"PROPOSAL-TEST-ONLY-NO-RELEASE-KEY-123456")
    unsigned = {
        "gate_version": processing.QUALITY_GATE_VERSION,
        "artifact_sha256": processing._sha(processing._quality_artifact(package)),
        "gate_decisions": dict.fromkeys(processing.MANDATORY_GATES, "PASS"),
        "valid_until": (NOW + timedelta(hours=1)).isoformat(),
    }
    package["quality_gate_manifest"] = dict(unsigned, hmac_sha256=processing._sign_quality_manifest(unsigned))
    assert processing._verified_quality_manifest(package, now=NOW)
    changed = deepcopy(package)
    changed["body"] += " A kivitelezés ára 900000 Ft."
    with pytest.raises(ValueError, match="quality_gate_manifest_artifact_mismatch"):
        processing._verified_quality_manifest(changed, now=NOW)
    changed = deepcopy(package)
    changed["source_urls"] = ["https://another.example/invented-source"]
    with pytest.raises(ValueError, match="quality_gate_manifest_artifact_mismatch"):
        processing._verified_quality_manifest(changed, now=NOW)


def _build_text(db, original, *, source_url="https://www.reddit.com/r/lakokozosseg/comments/1w8rs4c/munkadijak/", source_snapshot=None):
    topic = {
        "topic_id": "QRT-RUNTIME-NUMERIC", "brand_id": "Property360", "question": original,
        "source_url": source_url, "published_at": NOW - timedelta(hours=12),
        "published_at_raw": (NOW - timedelta(hours=12)).isoformat(),
        "freshness_decision": "CONTENT_SIGNAL", "eligibility_status": "eligible",
        "active_status": "unknown",
    }
    return revenue_policy.build_revenue_intent(
        topic, approved_brand_facts=processing._approved_brand_facts(db, "Property360", current=NOW),
        sales_goal="Konkrét projektadatokat tartalmazó egyeztetés.",
        next_step="Kérek telek–ház elővizsgálatot.", now=NOW, source_snapshot=source_snapshot,
    )


def test_runtime_handles_common_area_ranges_budget_and_deadlines_without_dropping_original(db):
    for original, expected in (
        ("Egy 35 m²-es szoba padlózásához keresek burkolót.", "megadott méretű szoba"),
        ("Egy 42 m2-es szoba festése mennyibe kerül?", "megadott méretű szoba"),
        ("A 10–15 cm homlokzati hőszigetelés költsége érdekel.", "eltérő vastagságú homlokzati hőszigetelés"),
        ("Megoldható a festés 900000 Ft-ból?", "megadott keretből"),
        ("Festést keresek 2 millió forintért.", "megadott összegért"),
        ("A keretem 3 millió a felújításra.", "megadott összeg"),
        ("Burkolót keresek, aki 3 héten belül el tudja kezdeni a munkát.", "megadott időn belül"),
        ("Két hét alatt megoldható a szoba festése?", "megadott idő alatt"),
        ("A felújítás 3 hónapja áll, másik kivitelezőt keresek.", "egy ideje áll"),
        ("A felújítási ajánlat 15%-kal magasabb, hogyan hasonlítsam össze?", "megadott aránnyal magasabb"),
    ):
        intent = _build_text(db, original)
        assert expected in intent["buyer_problem"], (original, intent["buyer_problem"])
        assert not re.search(r"\d", intent["buyer_problem"])
        assert intent["source_problem_evidence"]["original_problem"] == original
        assert intent["source_problem_evidence"]["original_text_sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest()
        assert not intent["publication_allowed"] and not intent["send_allowed"]


def test_actual_index_insulation_comparison_keeps_own_date_and_native_post(db):
    source_url = "https://forum.index.hu/Article/showArticle?t=9004917"
    _, links = catalog._page_evidence(
        (FIXTURE.parent / "index_building.html").read_text(encoding="utf-8"), base_url=source_url, limit=24000,
    )
    item = next(row for row in links if "a=172270043" in row["url"])
    original = item["label"].partition("[SOURCE_PAGE_EVIDENCE]")[0].strip()
    metadata = processing._source_page_metadata_from_label(item["label"])
    source = dict(metadata, source_url=item["url"], source_text=original,
                  published_at=processing._parse_observed_date(metadata["published_at_raw"], observed_at=NOW))
    intent = _build_text(db, original, source_url=item["url"], source_snapshot=source)
    assert "10 és 15 cm" in original
    assert "eltérő vastagságú homlokzati hőszigetelések között" in intent["buyer_problem"]
    assert "árkülönbözetet" in intent["buyer_problem"]
    evidence = intent["source_problem_evidence"]
    assert evidence["original_problem"] == original
    assert evidence["native_id"] == "172270043"
    assert evidence["published_at_raw"] == "2026.09.06 11:18:01"
    assert evidence["published_at"] == "2026-09-06T09:18:01+00:00"
    assert evidence["verification_mode"] == "source_refresh"


def test_uncommon_dimension_or_model_code_becomes_concrete_brief_with_original_evidence(db):
    original = "B30 falazattal épülne egy 6x8 garázs; hogyan hasonlítsam össze az ajánlatokat?"
    intent = _build_text(db, original)
    assert "garázs építése" in intent["buyer_problem"]
    assert "falazat megválasztása" in intent["buyer_problem"]
    assert "ajánlatok tartalmát" in intent["buyer_problem"]
    assert not re.search(r"\d", intent["buyer_problem"])
    assert intent["source_problem_evidence"]["original_problem"] == original
    assert intent["source_problem_evidence"]["public_problem_derivation"] == "topic_brief_with_original_evidence"
    unusual_suffix = _build_text(db, "A garázs 20 m²-rel bővülne; hogyan tervezzem meg?")
    assert "garázs építése" in unusual_suffix["buyer_problem"]
    assert "méretű-rel" not in unusual_suffix["buyer_problem"]
    assert unusual_suffix["source_problem_evidence"]["public_problem_derivation"] == "topic_brief_with_original_evidence"


def test_transformation_never_rescues_expired_or_changed_source_identity(db):
    original = "20 m²-es szobába keresek burkolót."
    for source in (
        {"source_url": "https://www.reddit.com/r/lakokozosseg/comments/1w8rs4c/munkadijak/", "published_at": NOW - timedelta(days=31)},
        {"source_url": "https://forum.index.hu/Article/viewArticle?a=172270043&t=9004917", "published_at": NOW - timedelta(hours=2)},
    ):
        with pytest.raises(revenue_policy.SourceReplenishmentRequired):
            _build_text(db, original, source_snapshot=dict(source, source_text=original))
