import pytest

from app.outbound_email_guard import OutboundEmailBlocked, require_plain_single_brand_email
from app.process_cards.adapters import build_approval_email


def test_approval_email_is_short_plain_and_single_brand() -> None:
    subject, body = build_approval_email(
        sender_email="Imperial Holding <info@imperialholding.hu>",
        title="Új munkaleírás",
        version=2,
        artifact_links={"pdf": "https://drive.google.com/file/d/example/view"},
    )

    assert subject == "Új anyag jóváhagyása"
    assert "Kérjük, nézze át" in body
    assert "Imperial Holding" in body
    assert "Process Card" not in body
    assert "checklist" not in body.casefold()


@pytest.mark.parametrize("phrase", [
    "korai fejlesztési jeleket",
    "auditigényeket",
    "API-t",
    "projektmenedzsmentet",
    "budget-checket",
    "due diligence-t",
    "white-label megoldást",
    "OEM konstrukciót",
    "SLA-t",
    "fit-out munkát",
    "partnercsatornát",
    "munkacsomagot",
    "BOM-ot",
    "DfMA-t",
    "projectcanary-t",
    "deduplikálást",
])
def test_guard_blocks_jargon_even_without_other_errors(phrase: str) -> None:
    with pytest.raises(OutboundEmailBlocked, match="jargon:"):
        require_plain_single_brand_email(
            sender_email="info@imperialholding.hu",
            subject="Rövid egyeztetés",
            body=(
                "Azért írunk, mert együttműködést keresünk. "
                f"{phrase} azonosítunk. Ez segít Önöknek. "
                "Kérjük, válaszoljanak. Imperial Holding"
            ),
        )


def test_guard_blocks_the_original_cross_brand_signature() -> None:
    with pytest.raises(OutboundEmailBlocked, match="foreign_brand"):
        require_plain_single_brand_email(
            sender_email="info@imperialholding.hu",
            subject="Ingatlanfejlesztési és műszaki partnerhálózat",
            body=(
                "Azért írunk, mert együttműködést keresünk. "
                "Ez segít Önöknek. Kérjük, válaszoljanak. "
                "Imperial Holding / Property360 / BauShield"
            ),
        )


def test_guard_blocks_unknown_product_name_in_sender_display() -> None:
    for sender in (
        "MyImperial <info@imperialholding.hu>",
        "Imperial Holding / MyImperial <info@imperialholding.hu>",
        "Imperial Holding Értesítések <info@imperialholding.hu>",
    ):
        with pytest.raises(OutboundEmailBlocked, match="sender_brand_mismatch"):
            build_approval_email(
                sender_email=sender,
                title="Új munkaleírás",
                version=1,
                artifact_links={},
            )
