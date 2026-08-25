from __future__ import annotations

import pytest

from app.services.outbound_copy_guard import (
    OutboundCopyViolation,
    check_outbound_email,
    brand_id_from_sender,
    require_outbound_email,
    require_sender_brand,
)


ALL_SIBLING_BRANDS = (
    "Imperial Intelligence",
    "Imperial Construction",
    "Imperial Knowledge",
    "Imperial Technologies",
    "Imperial Venture Studio",
    "Property 360",
    "BauShield",
    "Bautica",
    "Prefab",
    "ExitFlow",
    "Veritas Construct",
    "BauFreund",
    "Danish Fabrik",
    "Timberhaus",
    "Casa Moderna",
    "Everyday Homes",
    "Family Homes",
    "Budapesti Magasépítő Vállalat",
    "RED Property",
)


def test_simple_imperial_partner_email_passes() -> None:
    result = check_outbound_email(
        subject="Együttműködés ingatlanosokkal",
        body=(
            "Tisztelt Magyar Ingatlanszövetség!\n\n"
            "Keressük az együttműködés lehetőségét a MAISZ tagjaival. "
            "Ha valamelyik tagjuknak tervezőre vagy kivitelezőre van szüksége, "
            "tudunk segíteni.\n\n"
            "Kérjük, írják meg, mikor beszélhetünk erről röviden.\n\n"
            "Üdvözlettel:\nImperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert result.passed


def test_actual_maisz_copy_is_blocked_for_jargon_and_brand_leak() -> None:
    bad_body = "\n\n".join(
        [
            "Tisztelt Magyar Ingatlanszövetség!",
            (
                "Az Imperial Holding cégcsoport ingatlanfejlesztési, "
                "beruházás-előkészítési, "
                "generálkivitelezési és független műszaki kontrollfeladatokhoz keres "
                "strukturált szakmai együttműködést a MAISZ tagjaival."
            ),
            (
                "Saját projektfigyelő rendszerünk korai fejlesztési jeleket, telek- és "
                "ingatlantranzakciókat, aktív beruházásokat, garanciális és üzemeltetési "
                "auditigényeket azonosít. Ezekhez fejlesztői, értékbecslői, "
                "ingatlanközvetítői, műszaki, finanszírozási és üzemeltetési partnereket "
                "kívánunk kompetencia alapján rendelni."
            ),
            (
                "Kérjük, irányítsák megkeresésünket a tagsági vagy szakmai "
                "partnerkapcsolatokért felelős kollégához. Egy rövid online egyeztetésen "
                "bemutatjuk a projektjel-feldolgozási és ajánlási rendszert, valamint az "
                "együttműködés üzleti és ügyfélvédelmi kereteit."
            ),
            (
                "Üdvözlettel:\nImperial Holding / Property360 / BauShield szakmai csapata\n"
                "https://imperialholding.hu"
            ),
            (
                "Ha nem kívánnak hasonló szakmai megkeresést kapni, kérjük, jelezzék, "
                "és nem keressük Önöket újra."
            ),
        ]
    )

    result = check_outbound_email(
        subject="Ingatlanfejlesztési és műszaki partnerhálózat – konkrét projektekhez",
        body=bad_body,
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert not result.passed
    assert any(error.startswith("jargon:") for error in result.errors)
    assert "foreign_brand:baushield|property360" in result.errors


def test_imperial_email_cannot_name_a_sibling_brand() -> None:
    with pytest.raises(OutboundCopyViolation, match="foreign_brand:baushield"):
        require_outbound_email(
            subject="Rövid egyeztetés",
            body=(
                "Keressük az együttműködés lehetőségét. "
                "BauShield szolgáltatást ajánlunk. "
                "Ha műszaki segítségre van szükségük, tudunk segíteni. "
                "Kérjük, írják meg, mikor egyeztethetünk. Imperial Holding"
            ),
            brand_id="imperial-holding",
            kind="outreach",
        )


@pytest.mark.parametrize("sibling_brand", ALL_SIBLING_BRANDS)
def test_imperial_email_blocks_every_known_sibling_brand(sibling_brand: str) -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            f"A {sibling_brand} szolgáltatását is bemutatnánk. "
            "Ha szakmai segítségre van szükségük, tudunk segíteni. "
            "Kérjük, írják meg, mikor egyeztethetünk. Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert any(error.startswith("foreign_brand:") for error in result.errors)


@pytest.mark.parametrize(
    "inflected_brand",
    ("BauShielddel", "Bauticával", "Prefabbal", "Casa Modernával"),
)
def test_imperial_email_blocks_inflected_sibling_brand(inflected_brand: str) -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            f"A {inflected_brand} közös szolgáltatást ajánlanánk. "
            "Ha szakmai segítségre van szükségük, tudunk segíteni. "
            "Kérjük, írják meg, mikor egyeztethetünk. Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert any(error.startswith("foreign_brand:") for error in result.errors)


@pytest.mark.parametrize(
    "inflected_jargon",
    ("dashboardot", "stakeholdereket", "funnelt", "landinget", "referralt"),
)
def test_inflected_jargon_is_blocked(inflected_jargon: str) -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            f"A levél egy {inflected_jargon} is bemutatna. "
            "Ha szakmai segítségre van szükségük, tudunk segíteni. "
            "Kérjük, írják meg, mikor egyeztethetünk. Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert any(error.startswith("jargon:") for error in result.errors)


@pytest.mark.parametrize(
    "forbidden_term",
    (
        "API-t",
        "backendet",
        "frontendet",
        "endpointot",
        "deploymentet",
        "sprintet",
        "ticketet",
        "taskot",
        "projektmenedzsmentet",
        "projektkontrollt",
        "scope-ot",
    ),
)
def test_it_and_project_management_language_is_blocked(forbidden_term: str) -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            f"A levél egy {forbidden_term} is bemutatna. "
            "Ha szakmai segítségre van szükségük, tudunk segíteni. "
            "Kérjük, írják meg, mikor egyeztethetünk. Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert any(error.startswith("jargon:") for error in result.errors)


def test_paragraph_break_ends_a_sentence_without_punctuation() -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét ebben a témában: "
            "új családi ház tervezése és kivitelezése Budapest környékén\n\n"
            "Ha szakmai segítségre van szükségük, tudunk segíteni.\n\n"
            "Kérjük, írják meg, mikor egyeztethetünk.\n\n"
            "Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert "sentence_over_25_words" not in result.errors


def test_sender_brand_uses_exact_domain_boundaries() -> None:
    assert brand_id_from_sender("info@imperialholding.hu") == "imperial-holding"
    assert brand_id_from_sender("meghivas@tender.imperialholding.hu") == "imperial-holding"

    assert brand_id_from_sender("imperialholding@baushield.hu") == "baushield"
    with pytest.raises(OutboundCopyViolation, match="sender_brand_mismatch"):
        require_sender_brand("imperialholding@baushield.hu", "imperial-holding")
    with pytest.raises(OutboundCopyViolation, match="sender_brand_unknown"):
        brand_id_from_sender("info@imperialholding.evil.example")
    with pytest.raises(OutboundCopyViolation, match="sender_brand_mismatch"):
        require_sender_brand("info@baushield.hu", "imperial-holding")
    with pytest.raises(OutboundCopyViolation, match="sender_brand_mismatch"):
        require_sender_brand(
            "BauShield <info@imperialholding.hu>",
            "imperial-holding",
        )
    with pytest.raises(OutboundCopyViolation, match="sender_brand_mismatch"):
        require_sender_brand(
            "MyImperial <info@imperialholding.hu>",
            "imperial-holding",
        )
    with pytest.raises(OutboundCopyViolation, match="sender_brand_mismatch"):
        require_sender_brand(
            "Imperial Holding / MyImperial <info@imperialholding.hu>",
            "imperial-holding",
        )


def test_foreign_group_brand_url_is_blocked() -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            "Ha szakmai segítségre van szükségük, tudunk segíteni. "
            "Kérjük, nyissák meg ezt az oldalt: https://imperialintelligence.hu/kapcsolat. "
            "Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert "foreign_brand:imperial-intelligence" in result.errors


@pytest.mark.parametrize(
    "foreign_contact",
    (
        "info@imperialintelligence.hu",
        "info@veritasconstruct.hu",
        "info@danishfabrik.hu",
        "imperialintelligence.hu",
    ),
)
def test_foreign_group_brand_bare_domain_or_email_is_blocked(
    foreign_contact: str,
) -> None:
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            "Ha szakmai segítségre van szükségük, tudunk segíteni. "
            f"Kérjük, írjanak erre a címre: {foreign_contact}. "
            "Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert any(error.startswith("foreign_brand:") for error in result.errors)


def test_missing_recipient_benefit_or_next_step_blocks_send() -> None:
    result = check_outbound_email(
        subject="Együttműködési lehetőség",
        body="Szeretnénk bemutatni a vállalatunkat és a munkánkat.",
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert "recipient_benefit_not_clear" in result.errors
    assert "next_step_not_clear" in result.errors


def test_recipient_pronoun_alone_is_not_a_benefit() -> None:
    result = check_outbound_email(
        subject="Rövid bemutatkozás",
        body=(
            "Szeretnénk bemutatni a cégünket. "
            "Önöknek küldjük ezt a levelet. "
            "Kérjük, válaszoljanak. Imperial Holding"
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert "recipient_benefit_not_clear" in result.errors


def test_internal_email_also_requires_purpose_and_recipient_benefit() -> None:
    result = check_outbound_email(
        subject="Mai feladat",
        body="Kérjük, nézze át a listát. Imperial Holding",
        brand_id="imperial-holding",
        kind="internal",
    )

    assert "purpose_not_clear" in result.errors
    assert "recipient_benefit_not_clear" in result.errors


def test_sentence_over_25_words_blocks_send() -> None:
    long_sentence = " ".join(f"szó{index}" for index in range(26)) + "."
    result = check_outbound_email(
        subject="Rövid egyeztetés",
        body=(
            "Keressük az együttműködés lehetőségét. "
            f"{long_sentence} "
            "Ha segítségre van szükségük, tudunk segíteni. "
            "Kérjük, írják meg, mikor egyeztethetünk."
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert "sentence_over_25_words" in result.errors


def test_more_than_one_requested_action_blocks_send() -> None:
    result = check_outbound_email(
        subject="Együttműködési lehetőség",
        body=(
            "Keressük az együttműködés lehetőségét. "
            "Ha szakmai partnerre van szükségük, tudunk segíteni. "
            "Kérjük, küldjék el a bemutatkozásukat. "
            "Kérjük, írják meg, mikor egyeztethetünk."
        ),
        brand_id="imperial-holding",
        kind="outreach",
    )

    assert "multiple_next_steps" in result.errors
