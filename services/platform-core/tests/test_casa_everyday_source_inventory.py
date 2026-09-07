"""Verified Casa/Everyday inputs must reach the existing, brand-isolated CF path."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import select
from test_content_brand_form_regressions import intent_for, run_brand
from test_content_model_output_contract import NOW

from app import seed
from app.growth_ops import processing
from app.growth_ops.canonical_policy import assert_policy_integrity, publication_contract_for_brand
from app.growth_ops.revenue_policy import SourceReplenishmentRequired, evaluate_revenue_intent
from app.models import CopySourceRecord

EXPECTED = {
    "Casa Moderna": {
        "cta": "Építészkonzultációt kérek.",
        "proofs": {
            "1JWUFyUYqfTMCVwGDVETFTBBizjVbbrX0mTWht4a4Tlc": (
                "e9ab3339801b35ec7a1d5a897b1837fc9615acf8941a3a7f9c75c041b22a1683"
            ),
        },
    },
    "Everyday Homes": {
        "cta": "Kérek alaprajzi konzultációt.",
        "proofs": {
            "19DL0k4Cl-HHHylak9xfc9C0QYDXDJd60_zRu06fCdS4": (
                "4441675974379f9e8e45fa0d26ee62241ed2b14461f2a0fff9731f530170a958"
            ),
            "1RkxuxGVUvOPOsS3ytOG16UNRiD9RC4YpAv5Rj4e7UMc": (
                "41de607d2d822d1fe9e304d1e11c677e915ef63404fc21f4c673c23ecd70d170"
            ),
        },
    },
}


def manifest():
    return json.loads(
        (Path(seed.__file__).parent / "content_factory_source_manifest.json").read_text("utf8")
    )


def test_new_inventory_preserves_all_eleven_existing_source_records():
    inventory = manifest()
    existing = [row for row in inventory["brands"] if row["brand_id"] not in EXPECTED]
    encoded = json.dumps(existing, ensure_ascii=False, sort_keys=True).encode("utf8")
    assert hashlib.sha256(encoded).hexdigest() == (
        "527caa373935fe7b8799dcdd9ef26b3d51c1befc4d99eeef686e7df6a294e16d"
    )
    additions = [row for row in inventory["brands"] if row["brand_id"] in EXPECTED]
    assert {row["brand_id"] for row in additions} == set(EXPECTED)
    assert all(len(row["sources"]) == 1 for row in additions)
    assert all(row["sources"][0]["supersedes_versions"] == [] for row in additions)
    assert "Family Homes" not in {row["brand_id"] for row in inventory["brands"]}


@pytest.mark.parametrize("brand", EXPECTED)
def test_current_readback_proof_survives_seed_and_builds_distinct_usable_input(db, brand):
    facts = processing._approved_brand_facts(db, brand, current=NOW)
    assert len(facts) == 1
    fact = facts[0]
    proofs = fact["payload"]["source_evidence"]
    assert {row["drive_file_id"]: row["content_sha256"] for row in proofs} == (
        EXPECTED[brand]["proofs"]
    )
    assert all(row["all_excerpts_verified"] for row in proofs)
    assert all("private_source_path" not in row for row in proofs)
    assert any(EXPECTED[brand]["cta"] in excerpt
               for row in proofs for excerpt in row["exact_excerpts"])
    intent = intent_for(db, brand)
    assert evaluate_revenue_intent(intent, brand_id=brand)["eligible"]
    assert intent["brand_id"] == brand
    assert intent["next_step"] == EXPECTED[brand]["cta"]
    assert intent["radar_topic_id"] is None
    assert intent["input_type"] == "approved_brand_customer_problem"
    assert intent["publication_allowed"] is False and intent["send_allowed"] is False
    assert intent["source_refs"] == [fact["source_url"]]
    assert intent["buyer_problem"] == fact["payload"]["buyer_problems"][0]
    assert intent["sales_goal"] == fact["payload"]["sales_goal"]

    row = db.scalar(select(CopySourceRecord).where(
        CopySourceRecord.source_key == fact["source_key"],
    ))
    assert row.content_hash == hashlib.sha256(row.payload_json.encode()).hexdigest()
    original_id = row.id
    seed.seed_content_factory_source_inventory(db)
    db.flush()
    ids = list(db.scalars(select(CopySourceRecord.id).where(
        CopySourceRecord.source_key == fact["source_key"],
    )))
    assert ids == [original_id]


@pytest.mark.parametrize("brand,other", [
    ("Casa Moderna", "Everyday Homes"), ("Everyday Homes", "Casa Moderna"),
])
def test_other_brand_facts_cannot_authorize_the_new_brand_input(db, brand, other):
    assert intent_for(db, brand)["next_step"] == EXPECTED[brand]["cta"]
    for row in db.scalars(select(CopySourceRecord).where(CopySourceRecord.brand_id == brand)):
        row.approved = False
    db.flush()
    assert processing._approved_brand_facts(db, other, current=NOW)
    assert processing._approved_brand_facts(db, brand, current=NOW) == []
    with pytest.raises(SourceReplenishmentRequired, match="approved_brand_fact_missing"):
        intent_for(db, brand)


def test_two_contracts_agree_with_current_sources_without_unsupported_delivery_promise():
    casa = publication_contract_for_brand("Casa Moderna")
    everyday = publication_contract_for_brand("Everyday Homes")
    assert "Építészvezérelt" in casa["position"]
    assert "építészet, enteriőr és személyes concierge" in casa["position"]
    assert "Építészkonzultációt kérek." in " ".join(casa["required"])
    assert "Privát konzultációt kérek." not in json.dumps(casa, ensure_ascii=False)
    assert "egy kézben" not in everyday["position"]
    assert "alaprajzi rutinok, tárolás" in everyday["position"]
    assert "Kérek alaprajzi konzultációt." in " ".join(everyday["required"])
    assert "Family Homes karakter- és napirend-mechanizmusa" in everyday["forbidden"]
    assert_policy_integrity()


def copy_for(intent):
    """Offline copy fixtures: source-bound advice, not a claimed live model result."""
    if intent["brand_id"] == "Casa Moderna":
        title = "Egyedi ház: az építészeti és belsőépítészeti igények találkozása"
        body = (
            "Az alaprajz átnézésekor érdemes megnevezni, mely helyiségek kapcsolata fontos Önnek. "
            "A közös étkezés, a csendes munkavégzés és a vendégfogadás eltérő térigényt adhat. "
            "Ezek tisztázása segíthet abban, hogy a tervezési megbeszélés konkrét "
            "helyzetekről szóljon.\n\n"
            "Gyűjtse össze, mi tetszik Önnek egy térben, és mi az, amit a jelenlegi otthonában "
            "másként használna. Külön jelölje a világításhoz, az anyagokhoz és a tároláshoz "
            "kapcsolódó elképzeléseit. A belső tér igényeit az építészeti döntésekkel együtt "
            "érdemes megvizsgálni, hogy az egyeztetésen a kapcsolódó kérdések is előkerüljenek.\n\n"
            "A konzultációhoz készítse elő a telek ismert adatait, a tervezett szobák listáját "
            "és azokat a kérdéseket, amelyekben még nincs döntése. A személyes igényekből "
            "így áttekinthető tervezési kiindulópont készülhet."
        )
        social = (
            "Egyedi családi ház tervezésekor a belső tér használatát az építészeti igényekkel "
            "együtt érdemes tisztázni. Gondolja végig, hol étkezne, dolgozna és fogadna vendéget. "
            "A Casa Moderna építészvezérelt megközelítésében az építészet és az enteriőr "
            "egy folyamat része. Készítse elő a telek ismert adatait és tervezési kérdéseit. "
            "Építészkonzultációt kérek. #CasaModerna #építészet #otthon"
        )
    else:
        title = "Praktikus családi otthon: tárolás a napi útvonalak mellett"
        body = (
            "Érdemes felírnod, mi érkezik veletek az ajtón át: kabát, cipő, táska vagy bevásárlás. "
            "Jelöld az alaprajzon, hol tudnád ezeket letenni, és merre indulsz tovább velük. "
            "A tároló helye akkor vizsgálható jól, ha a használat útvonalát is látod mellette.\n\n"
            "A kamránál gondold végig, mit veszel elő főzés közben, és mi kerül ritkábban "
            "az asztalra. A háztartási helyiségben a mosás, szárítás és elpakolás egymást "
            "követő lépéseit nézd át. A tárgylista és a folyamatlista segíthet megnevezni "
            "a tárolási igényeidet anélkül, hogy előre kész helyiségméretből indulnál ki.\n\n"
            "Az alaprajzi konzultációra vidd magaddal a meglévő tervet, ha van, és a napi "
            "térhasználatod rövid leírását. Jelezd, hol szoktak felhalmozódni a tárgyak, "
            "és mely útvonalak keresztezik egymást. Ezekből konkrét elrendezési kérdések "
            "fogalmazhatók meg a tervezéshez."
        )
        social = (
            "Hová kerül a táska, a kabát és a bevásárlás, amikor hazaértek? A praktikus "
            "családi otthon alaprajzán a tárolást a napi útvonalakkal együtt érdemes átnézni. "
            "Írd össze a gyakran használt tárgyakat, és jelöld, hol lenne rájuk szükséged. "
            "Az Everyday Homes a mindennapi használatból indul ki. Kérek alaprajzi konzultációt. "
            "#EverydayHomes #otthon #alaprajz"
        )
    return {
        "title": title,
        "body": intent["buyer_problem"] + " "
        + intent["approved_brand_facts"][0]["payload"]["statement"] + "\n\n" + body,
        "facebook_post": social,
        "cta": {"label": intent["next_step"], "intent": "lead"},
    }


@pytest.mark.parametrize("brand", EXPECTED)
def test_real_source_input_reaches_generation_and_review_with_its_exact_cta(db, monkeypatch, brand):
    def generate(request, system):
        assert request["revenue_intent"]["brand_id"] == brand
        assert request["revenue_intent"]["next_step"] == EXPECTED[brand]["cta"]
        assert "MAGÁZD" in system if brand == "Casa Moderna" else "TEGEZD" in system
        return {"package": copy_for(request["revenue_intent"])}

    result, row, calls = run_brand(db, monkeypatch, brand, generate)
    assert result["generated"] == 1, row.evidence_json
    assert len(calls) == 2
    output = json.loads(row.evidence_json)
    assert output["cta"]["label"] == EXPECTED[brand]["cta"]
    assert output["revenue_intent"]["brand_id"] == brand
    assert output["revenue_intent"]["publication_allowed"] is False
    assert output["revenue_intent"]["send_allowed"] is False
    assert all(fact["brand_id"] == brand
               for fact in output["revenue_intent"]["approved_brand_facts"])
    assert calls[-1]["request"]["artifact"] == processing._quality_artifact(output)


@pytest.mark.parametrize("brand", EXPECTED)
def test_new_source_never_authorizes_forged_model_permission_metadata(db, monkeypatch, brand):
    def generate(request, system):
        del system
        intent = request.get("revenue_intent") or request["trusted_revenue_intent"]
        package = copy_for(intent)
        package["revenue_intent"] = dict(deepcopy(intent), publication_allowed=True)
        return {"package": package}

    result, row, calls = run_brand(db, monkeypatch, brand, generate)
    assert result["generated"] == 0
    assert len(calls) == 3  # Initial copy and the existing two repairs; no review/publication.
    assert all("release_review" not in call["purpose"] for call in calls)
    assert "model_revenue_metadata_untrusted" in row.evidence_json
