from __future__ import annotations

# ruff: noqa: E501
import hashlib
import json
import os
from pathlib import Path

import pytest

from app.growth_ops.canonical_policy import ACTIVE_CONTENT_BRANDS
from app.growth_ops.canonical_templates import CanonicalFirstContactRegistry
from app.growth_ops.registry import GrowthRegistryError

REGISTRY_PATH = (
    Path(os.environ["CANONICAL_FIRST_CONTACT_REGISTRY_FILE"])
    if "CANONICAL_FIRST_CONTACT_REGISTRY_FILE" in os.environ
    else Path(__file__).resolve().parents[3]
    / "config"
    / "outbound"
    / "canonical_first_contact_templates_hu_v1.json"
)

ARCHITECT_BODY = """Tisztelt XY!

Azért kerestük fel az Ön irodáját, mert láttuk munkáit (XY, CC, ZZ), és szeretnénk Önnel együttműködni.

Cégünk, az XY 1989 óta foglalkozik családi házak generálkivitelezésével, készházak építésével.

Szeretnénk bővíteni a tervezői kapcsolatainkat, mert jelenleg kapacitáshiánnyal küzdünk ezen a területen – és az Ön által tervezett házakhoz is szívesen kapcsolódnánk kivitelezőként.

Van szabad kapacitása? Érdekli az együttműködés?"""

LAND_OWNER_BODY = """Tisztelt [Név]!
Cégünk, az Imperial Holding, előregyártott készházak és típusházak építésével foglalkozik, és úgy gondoljuk, hogy az Ön telkében van lehetőség.
Szívesen felvennénk a kínálatunkba DÍJMENTESEN, mert sokan keresnek nálunk a típusházakhoz eladó telkeket.
Itt meg tudja nézni a weboldalunkon, milyen telkekkel dolgozunk jelenleg: https://imperialholding.hu/termek/telek-kereso
Nem kérünk Öntől pénzt semmilyen formában, jutalékot sem: a lehetőség mindkettőnknek előnyös, mi a típusházat adjuk el, Ön pedig a telket. Nem kérünk semmilyen kötelezettséget, csak szeretnénk együttműködni Önnel.
Érdekli?
Üdvözlettel:
Imperial Holding
info@imperialholding.hu
Leiratkozás: [egyedi leiratkozási link]"""

REAL_ESTATE_AGENT_BODY = """Tisztelt [Név]!
Cégünk, az Imperial Holding, előregyártott készházak és típusházak építésével foglalkozik, és úgy gondoljuk, hogy az Ön által hirdetett telekben van lehetőség.
2,5% jutalékot fizetünk azoknak az ingatlanos partnereinknek, akik a hirdetett telkeik mellé valamelyik típusházunkat is eladják.
Jelenleg is számos ingatlan-irodával dolgozunk együtt az ország minden pontján. Mi elkészítjük a hirdetést Önnek egy olyan típusházzal, ami építhető erre a telekre, látványtervvel, alaprajzzal és műszaki leírással. Ha Ön meghirdeti a telekkel együtt, és érkezik rá vevő, 2,5% jutalékot fizetünk Önnek a típusterv árából.
Érdekli ez a lehetőség?
Üdvözlettel:
Imperial Holding
info@imperialholding.hu
Leiratkozás: [egyedi leiratkozási link]"""

REFERRAL_PARTNER_BODY = """Tisztelt [Név]!

Cégünk 1989 óta családi házak, készházak kulcsrakész kivitelezésével foglalkozik, és új partnereket keresünk.

Kidolgoztunk egy rendszert, amelyben olyan partnerek tudnak ajánlani bennünket, akiknél a mi célpiacunk megfordul - és ezért 2,5% jutalékot fizetünk. Egy átlagos 50 milliós családi ház esetében 1 250 000 forintot.

Az Önök [konkrét üzlet/hálózat/termékkör] vásárlói között rendszeresen megjelennek teljesen új házat építeni akaró, vagy nagy felújítást tervező ügyfelek. Mi mindkettőnek tudunk segíteni. Az Imperial PartnerPonttal az Ön üzlete egy saját kódot kap. Ezt átadják az ügyfélnek - semmi más dolguk nincs vele - és mi onnantól átvesszük az egészet. A folyamat az Önök számára is végig nyomon követhető - nyilvántartást vezetünk minden megkeresésről.

Ha az ajánlásból szerződés lesz, 2,5% jutalékot fizetünk egy összegben Önöknek. Érdekli ez a lehetőség, beszéljünk róla? Dolgozott már hasonlóval?"""

ARCHITECT_BOLD = (
    "Szeretnénk bővíteni a tervezői kapcsolatainkat, mert jelenleg "
    "kapacitáshiánnyal küzdünk ezen a területen – és az Ön által tervezett "
    "házakhoz is szívesen kapcsolódnánk kivitelezőként."
)
AGENT_BOLD = (
    "2,5% jutalékot fizetünk azoknak az ingatlanos partnereinknek, akik a "
    "hirdetett telkeik mellé valamelyik típusházunkat is eladják."
)
REFERRAL_COMMISSION_BOLD = (
    "és ezért 2,5% jutalékot fizetünk. Egy átlagos 50 milliós családi ház "
    "esetében 1 250 000 forintot."
)
REFERRAL_EASE_BOLD = "semmi más dolguk nincs vele"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _registry() -> CanonicalFirstContactRegistry:
    return CanonicalFirstContactRegistry.load(REGISTRY_PATH)


def _render(registry: CanonicalFirstContactRegistry, **changes):
    data = {
        "recipient_type": "architect_office",
        "recipient_name": "Minta Építésziroda",
        "sender_company_name": "Imperial Holding",
        "reference_names": ["Referencia Ház", "Második Ház"],
        "reference_names_verified": True,
        "business_context": None,
        "business_context_verified": False,
        "business_context_evidence_url": None,
        "unsubscribe_url": None,
        "recipient_classification_verified": True,
        "exclusion_screening_verified": True,
        "screening_values": ["Minta Építésziroda", "iroda@example.test"],
    }
    data.update(changes)
    return registry.render(**data)


def test_registry_contains_only_owner_approved_exact_canonical_texts():
    registry = _registry()
    expected = {
        "ARCHITECT_OFFICE_FIRST_CONTACT_HU": (
            "architect_office",
            "együttműködés",
            "906da7ca17aa2f81d7db42ccf826db301ab498a5984c0408197f76731e3071bb",
            ARCHITECT_BODY,
            "3e1bc84d24270e3da52e943d5c2325889805cff4a3e3eda6a1427daa253eab10",
            500,
        ),
        "LAND_OWNER_FIRST_CONTACT_HU": (
            "land_owner",
            "szeretnék érdeklődni a telek iránt",
            "792451ca4fd342fdf19cf530caa910030e8a5e06f96eec39f3b02700ea4159e5",
            LAND_OWNER_BODY,
            "aa1894dfc0a53401d3fdd5c737cbdf737acea3d325d44eb38f70b36474703500",
            763,
        ),
        "REAL_ESTATE_AGENT_FIRST_CONTACT_HU": (
            "real_estate_agent",
            "ház eladásában kérnék segítséget",
            "4f5460a60567e226c1fb4c4e4a28b59315738a2eda21ce37eebdbf6d28b43334",
            REAL_ESTATE_AGENT_BODY,
            "9df3c674a73e346a122c60162af06f73cfd55e6da49596c89f3ccbd25e8ade8d",
            811,
        ),
        "REFERRAL_PARTNER_FIRST_CONTACT_HU": (
            "referral_partner",
            "együttműködés",
            "906da7ca17aa2f81d7db42ccf826db301ab498a5984c0408197f76731e3071bb",
            REFERRAL_PARTNER_BODY,
            "21eb74dc15610754cef51e44af0f2553b0437127864e6fa965e1748a277d90c4",
            1030,
        ),
    }

    assert set(registry.templates_by_id) == set(expected)
    for template_id, (
        recipient_type,
        subject,
        subject_digest,
        body,
        digest,
        byte_count,
    ) in expected.items():
        template = registry.templates_by_id[template_id]
        assert template["recipient_type"] == recipient_type
        assert template["status"] == ["OWNER_APPROVED", "CANONICAL"]
        assert template["origin"] == "HUMAN_AUTHORED_LOCKED"
        assert template["ai_modification_allowed"] is False
        assert template["subject"] == subject
        expected_subject_status = (
            "OWNER_APPROVED_IMMUTABLE"
            if template_id == "REFERRAL_PARTNER_FIRST_CONTACT_HU"
            else "OWNER_APPROVED"
        )
        assert template["subject_status"] == expected_subject_status
        assert _sha(subject) == subject_digest
        assert template["owner_approved_body_text"] == body
        assert _sha(body) == digest
        assert len(body.encode("utf-8")) == byte_count

    legacy = registry.raw["archived_templates"][0]
    assert legacy["template_id"] == "PARTNERPOINT_LEGACY_1_PERCENT_FIRST_CONTACT_HU"
    assert legacy["status"] == ["ARCHIVED", "DEACTIVATED"]
    assert legacy["active"] is False
    assert legacy["fallback_allowed"] is False
    assert legacy["replaced_by"] == "REFERRAL_PARTNER_FIRST_CONTACT_HU"


def test_registry_requires_the_exact_fail_closed_brand_isolation_policy(tmp_path):
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    raw.pop("brand_isolation_policy")
    candidate = tmp_path / "canonical.json"
    candidate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GrowthRegistryError, match="brand-isolation policy is missing"):
        CanonicalFirstContactRegistry.load(candidate)


def test_registry_rejects_a_weakened_brand_isolation_policy(tmp_path):
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    raw["brand_isolation_policy"]["sender_brands"]["imperial"][
        "forbidden_customer_facing_terms"
    ].remove("Prefab")
    candidate = tmp_path / "canonical.json"
    candidate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GrowthRegistryError, match="brand-isolation policy changed"):
        CanonicalFirstContactRegistry.load(candidate)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["hard_gates"][2]["normalized_word_any"].remove("gdn"),
        lambda raw: raw["hard_gates"][1]["normalized_all_any"][1].remove(
            "budapest xii kerulet"
        ),
        lambda raw: raw["hard_gates"][3]["normalized_any"].remove("kurucz hajnalka"),
    ],
)
def test_registry_rejects_any_weakened_hard_gate_definition(tmp_path, mutate):
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    mutate(raw)
    candidate = tmp_path / "canonical.json"
    candidate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GrowthRegistryError, match="hard-gate policy changed"):
        CanonicalFirstContactRegistry.load(candidate)


def test_registry_rejects_self_authenticated_owner_body_tampering(tmp_path):
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    template = next(
        item
        for item in raw["templates"]
        if item["template_id"] == "LAND_OWNER_FIRST_CONTACT_HU"
    )
    template["owner_approved_body_text"] += "\nNem jóváhagyott toldás."
    body_bytes = template["owner_approved_body_text"].encode("utf-8")
    template["owner_approved_body_text_sha256_utf8"] = hashlib.sha256(
        body_bytes
    ).hexdigest()
    template["owner_approved_body_text_utf8_bytes"] = len(body_bytes)
    candidate = tmp_path / "canonical.json"
    candidate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(GrowthRegistryError, match="registry byte hash changed"):
        CanonicalFirstContactRegistry.load(candidate)


def test_architect_render_replaces_only_approved_variables_and_bolds_exact_sentence():
    rendered = _render(_registry())
    expected = (
        ARCHITECT_BODY.replace("Tisztelt XY!", "Tisztelt Minta Építésziroda!")
        .replace("(XY, CC, ZZ)", "(Referencia Ház, Második Ház)")
        .replace("Cégünk, az XY 1989", "Cégünk, az Imperial Holding 1989")
    )

    assert rendered.template_id == "ARCHITECT_OFFICE_FIRST_CONTACT_HU"
    assert rendered.subject == "együttműködés"
    assert rendered.body_text == expected
    assert f"<strong>{ARCHITECT_BOLD}</strong>" in rendered.body_html
    assert rendered.sendable is True


def test_architect_zero_reference_uses_the_single_approved_fallback_sentence():
    rendered = _render(_registry(), reference_names=[])

    assert "mert láttuk munkáit, és szeretnénk" in rendered.body_text
    assert "(XY, CC, ZZ)" not in rendered.body_text


def test_one_architect_reference_fails_closed():
    with pytest.raises(GrowthRegistryError, match="zero_two_or_three"):
        _render(_registry(), reference_names=["Egyetlen Ház"])


def test_unverified_architect_references_fail_closed():
    with pytest.raises(GrowthRegistryError, match="references_not_verified"):
        _render(_registry(), reference_names_verified=False)


def test_architect_sender_company_must_match_the_imperial_sender_brand():
    with pytest.raises(
        GrowthRegistryError,
        match="canonical_sender_company_conflicts_with_sender_brand_no_send",
    ):
        _render(_registry(), sender_company_name="Prefab")


@pytest.mark.parametrize(
    ("recipient_type", "body", "subject", "bold_sentence"),
    [
        (
            "land_owner",
            LAND_OWNER_BODY,
            "szeretnék érdeklődni a telek iránt",
            None,
        ),
        (
            "real_estate_agent",
            REAL_ESTATE_AGENT_BODY,
            "ház eladásában kérnék segítséget",
            AGENT_BOLD,
        ),
    ],
)
def test_land_templates_and_owner_approved_subjects_are_exact(
    recipient_type: str,
    body: str,
    subject: str,
    bold_sentence: str | None,
):
    rendered = _render(
        _registry(),
        recipient_type=recipient_type,
        recipient_name="Kovács Anna",
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        unsubscribe_url="https://intelligence.example/growth/unsubscribe/token",
    )
    expected = body.replace("[Név]", "Kovács Anna").replace(
        "[egyedi leiratkozási link]",
        "https://intelligence.example/growth/unsubscribe/token",
    )

    assert rendered.body_text == expected
    assert rendered.subject == subject
    assert rendered.sendable is True
    assert rendered.blocked_reasons == ()
    if bold_sentence:
        assert f"<strong>{bold_sentence}</strong>" in rendered.body_html


def test_referral_partner_render_is_exact_and_only_replaces_the_two_allowed_fields():
    rendered = _render(
        _registry(),
        recipient_type="referral_partner",
        recipient_name="Kovács Anna",
        sender_company_name=None,
        reference_names=[],
        reference_names_verified=False,
        business_context="építőanyag-áruházi hálózat",
        business_context_verified=True,
        business_context_evidence_url="https://example.test/uzleteink",
    )
    expected = REFERRAL_PARTNER_BODY.replace("[Név]", "Kovács Anna").replace(
        "[konkrét üzlet/hálózat/termékkör]",
        "építőanyag-áruházi hálózat",
    )

    assert rendered.template_id == "REFERRAL_PARTNER_FIRST_CONTACT_HU"
    assert rendered.subject == "együttműködés"
    assert rendered.body_text == expected
    assert rendered.body_text.split("\n\n") == expected.split("\n\n")
    assert "\n\n\n" not in rendered.body_text
    assert f"<strong>{REFERRAL_COMMISSION_BOLD}</strong>" in rendered.body_html
    assert f"<strong>{REFERRAL_EASE_BOLD}</strong>" in rendered.body_html
    assert rendered.body_html.count("<strong>") == 2
    assert rendered.sendable is True


@pytest.mark.parametrize(
    ("business_context", "blocked_brand"),
    [
        ("Prefab értékesítési hálózat", "Prefab"),
        ("Pre\u200bfab értékesítési hálózat", "Prefab"),
        ("RED Property értékesítési hálózat", "RED Property"),
        ("Imperial Intelligence értékesítési hálózat", "Imperial Intelligence"),
    ],
)
def test_verified_variable_cannot_inject_a_second_customer_facing_brand(
    business_context, blocked_brand
):
    with pytest.raises(
        GrowthRegistryError,
        match=rf"cross_brand_customer_facing_content_no_send:{blocked_brand}",
    ):
        _render(
            _registry(),
            recipient_type="referral_partner",
            recipient_name="Kovács Anna",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            business_context=business_context,
            business_context_verified=True,
            business_context_evidence_url="https://example.test/uzleteink",
        )


def test_every_non_imperial_active_brand_and_its_concatenated_form_is_blocked():
    registry = _registry()
    forbidden_terms = registry.raw["brand_isolation_policy"]["sender_brands"][
        "imperial"
    ]["forbidden_customer_facing_terms"]

    for brand in ACTIVE_CONTENT_BRANDS:
        if brand == "Imperial":
            continue
        assert brand in forbidden_terms
        for candidate in {brand, brand.replace(" ", "")}:
            with pytest.raises(
                GrowthRegistryError,
                match="cross_brand_customer_facing_content_no_send",
            ):
                _render(
                    registry,
                    recipient_type="referral_partner",
                    recipient_name="Kovács Anna",
                    sender_company_name=None,
                    reference_names=[],
                    reference_names_verified=False,
                    business_context=f"{candidate} értékesítési hálózat",
                    business_context_verified=True,
                    business_context_evidence_url="https://example.test/uzleteink",
                )


@pytest.mark.parametrize(
    "alias",
    [
        "bautica.hu",
        "casa-moderna.hu",
        "baufreund.hu",
        "danishfabrik.hu",
        "timberhaus.hu",
        "red-property",
        "property-360",
        "everyday-homes",
        "venture-studio",
        "family-homes",
        "imperial-construction",
        "imperial-intelligence",
        "imperial-technologies",
        "imperial-knowledge",
        "exitflow.hu",
        "veritas-construct",
        "baushield.hu",
    ],
)
def test_common_slug_and_domain_aliases_cannot_bypass_brand_isolation(alias):
    with pytest.raises(
        GrowthRegistryError,
        match="cross_brand_customer_facing_content_no_send",
    ):
        _render(
            _registry(),
            recipient_type="referral_partner",
            recipient_name="Kovács Anna",
            sender_company_name=None,
            reference_names=[],
            reference_names_verified=False,
            business_context=f"{alias} értékesítési hálózat",
            business_context_verified=True,
            business_context_evidence_url="https://example.test/uzleteink",
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"business_context": None},
        {"business_context_verified": False},
        {"business_context_evidence_url": None},
    ],
)
def test_referral_partner_missing_or_unverified_business_context_fails_closed(changes):
    data = {
        "recipient_type": "referral_partner",
        "recipient_name": "Kovács Anna",
        "sender_company_name": None,
        "reference_names": [],
        "reference_names_verified": False,
        "business_context": "építőanyag-áruházi hálózat",
        "business_context_verified": True,
        "business_context_evidence_url": "https://example.test/uzleteink",
    }
    data.update(changes)

    with pytest.raises(GrowthRegistryError, match="template-variable-missing|evidence URL"):
        _render(_registry(), **data)


@pytest.mark.parametrize(
    ("screening_values", "gate_id"),
    [
        (["Turczer József"], "BLOCK_TURCZER_JOZSEF"),
        (["József Turczer"], "BLOCK_TURCZER_JOZSEF"),
        (["Otthon Centrum", "Budapest II. kerületi iroda"], "BLOCK_OTTHON_CENTRUM"),
        (["Otthon Centrum", "II. kerületi iroda"], "BLOCK_OTTHON_CENTRUM"),
        (["Otthon Centrum", "II/A. kerületi iroda"], "BLOCK_OTTHON_CENTRUM"),
        (["Otthon Centrum", "2-A kerületi iroda"], "BLOCK_OTTHON_CENTRUM"),
        (["Otthon Centrum", "XII. kerületi iroda"], "BLOCK_OTTHON_CENTRUM"),
        (["OC.hu", "Budapest II/A. kerületi iroda"], "BLOCK_OTTHON_CENTRUM"),
        (["OC.hu", "1024 Budapest, Bem rakpart"], "BLOCK_OTTHON_CENTRUM"),
        (["OC.hu", "1126 Budapest, MOM Park"], "BLOCK_OTTHON_CENTRUM"),
        (["GDN Ingatlanhálózat – Bármely iroda"], "BLOCK_GDN_INGATLANHALOZAT"),
        (["G.D.N. Ingatlanhálózat"], "BLOCK_GDN_INGATLANHALOZAT"),
        (["TurczerJózsef"], "BLOCK_TURCZER_JOZSEF"),
        (["JózsefTurczer"], "BLOCK_TURCZER_JOZSEF"),
        (["LeierHungária Kft."], "BLOCK_LEIER_INCIDENT_CONTAINMENT"),
        (["LEIERHUNGARIA"], "BLOCK_LEIER_INCIDENT_CONTAINMENT"),
        (["LeierGroup"], "BLOCK_LEIER_INCIDENT_CONTAINMENT"),
        (["https://g-d-n.hu/iroda"], "BLOCK_GDN_INGATLANHALOZAT"),
        (
            ["Leier Hungária Kft.", "info@leier.hu"],
            "BLOCK_LEIER_INCIDENT_CONTAINMENT",
        ),
    ],
)
def test_named_hard_gates_run_before_template_render(screening_values, gate_id):
    with pytest.raises(GrowthRegistryError, match=gate_id):
        _render(_registry(), screening_values=screening_values)


def test_hard_gate_does_not_confuse_budapest_iii_with_budapest_ii():
    assert _registry().hard_gate_match(
        ["Otthon Centrum", "Budapest III. kerületi iroda"]
    ) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient_type": "unknown"},
        {"recipient_classification_verified": False},
        {"exclusion_screening_verified": False},
    ],
)
def test_uncertain_or_unscreened_recipient_fails_closed(changes):
    with pytest.raises(GrowthRegistryError):
        _render(_registry(), **changes)
