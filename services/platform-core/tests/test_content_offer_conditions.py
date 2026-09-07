"""Prevent the actual provider's unsupported no-obligation promise recurring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_content_model_output_contract import _copy_only, _run

from app import seed
from app.growth_ops import processing
from app.growth_ops.canonical_policy import publication_contract_for_brand

REAL_PROVIDER_ENDING = (
    "Ha szeretnéd, hogy a telek, a terv és a pénz ne egymás ellen dolgozzon, "
    "hanem együtt, akkor kérd a telek–ház elővizsgálatot. "
    "Ezzel nem vállalsz semmit, csak megkapod a választ a kérdéseidre."
)
SAFE_CONDITION = "A megkeresés feltételeit és esetleges költségét érdemes előre tisztázni."


def _condition_errors(text: str, *, field: str = "body", metadata=None):
    package = {"brand_id": "Property360", "body": SAFE_CONDITION}
    package.update(metadata or {})
    if field == "cta":
        package["cta"] = {"label": text, "intent": "lead"}
    else:
        package[field] = text
    return processing._deterministic_publication_errors(
        package, publication_contract_for_brand("Property360"),
    )


@pytest.mark.parametrize("field", ["title", "body", "facebook_post", "cta"])
def test_real_provider_promise_is_rejected_in_every_public_text_field(field):
    assert "unverified_offer_condition" in _condition_errors(REAL_PROVIDER_ENDING, field=field)


@pytest.mark.parametrize("promise", [
    "Az elővizsgálat kötelezettségmentes.",
    "A megkeresés semmire sem kötelez.",
    "Az ajánlatkérés nem jár semmilyen kötelezettséggel.",
    "Az elővizsgálatot ingyenesen adjuk.",
    "Díjmentes konzultációt kérhetsz.",
    "A műszaki kalkuláció nem kerül semmibe.",
    "Az ajánlatkérés nem kötelez semmire.",
    "Ezzel nem vállalsz kötelezettséget.",
])
def test_obligation_and_fee_promises_are_recognized_in_hungarian_variants(promise):
    assert "unverified_offer_condition" in _condition_errors(promise)


def test_model_claim_annotations_cannot_authorize_the_unsupported_offer():
    errors = _condition_errors(REAL_PROVIDER_ENDING, metadata={
        "offer_conditions_verified": True,
        "offer_conditions": {"free": True, "no_obligation": True},
        "source_urls": ["https://docs.google.com/document/d/invented-source/edit"],
        "quality_gate_manifest": {"claim_coverage": "PASS"},
    })
    assert "unverified_offer_condition" in errors


@pytest.mark.parametrize("text", [
    SAFE_CONDITION,
    "Kérek telek–ház elővizsgálatot.",
    "Az egyeztetés előtt érdemes rákérdezni, hogy díjmentes-e az elővizsgálat.",
    "Az elővizsgálat nem ingyenes; a feltételeit előre tisztázni kell.",
])
def test_documented_request_and_cautious_condition_language_are_retained(text):
    assert "unverified_offer_condition" not in _condition_errors(text)


def test_all_nine_real_brand_ctas_survive_the_new_offer_condition_check():
    manifest = json.loads(
        (Path(seed.__file__).parent / "content_factory_source_manifest.json").read_text("utf8")
    )
    checked_brands = set()
    for brand in manifest["brands"]:
        for source in brand["sources"]:
            payload = source["payload"]
            for step in payload.get("next_steps") or [payload.get("next_step")]:
                if not step:
                    continue
                package = {
                    "brand_id": brand["brand_id"], "body": SAFE_CONDITION,
                    "cta": {"label": step, "intent": "lead"},
                }
                errors = processing._deterministic_publication_errors(
                    package, publication_contract_for_brand(brand["brand_id"]),
                )
                assert "unverified_offer_condition" not in errors, (brand["brand_id"], step)
                checked_brands.add(brand["brand_id"])
    assert len(checked_brands) == 9


def test_actual_bad_ending_goes_to_existing_repair_before_review(db, monkeypatch):
    def generate(request):
        intent = request.get("revenue_intent") or request["trusted_revenue_intent"]
        package = _copy_only(intent)
        if "repair_round" not in request:
            package["body"] += " " + REAL_PROVIDER_ENDING
        else:
            assert "unverified_offer_condition" in request["gate_errors"]
            package["body"] += " " + SAFE_CONDITION
        return {"package": package}

    result, row, calls = _run(db, monkeypatch, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 3  # generation, existing repair, independent review
    reviewed = calls[-1][1]["artifact"]
    assert SAFE_CONDITION in reviewed["body"]
    assert "nem vállalsz semmit" not in reviewed["body"]
    assert row.status == "release_passed"


def test_persistently_bad_promise_stops_after_existing_two_repairs_without_review(db, monkeypatch):
    def generate(request):
        intent = request.get("revenue_intent") or request["trusted_revenue_intent"]
        package = _copy_only(intent)
        package["body"] += " " + REAL_PROVIDER_ENDING
        return {"package": package}

    result, row, calls = _run(db, monkeypatch, generate)
    assert result["generated"] == 0
    assert len(calls) == 3  # generation and exactly two existing repair attempts
    assert all("release_review" not in purpose for purpose, _request in calls)
    assert "unverified_offer_condition" in row.evidence_json
    assert row.content_asset_id is None
