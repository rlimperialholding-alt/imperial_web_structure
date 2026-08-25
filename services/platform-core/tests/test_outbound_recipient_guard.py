from app.services.outbound_recipient_guard import (
    ALLOWED,
    OWNER_HARD_SUPPRESSION,
    PUBLIC_AUTHORITY_HARD_SUPPRESSION,
    SUPPRESSION_REVIEW,
    RecipientPolicyContext,
    evaluate_outbound_recipient,
)


def decision(**changes):
    return evaluate_outbound_recipient(RecipientPolicyContext(**changes))


def test_turczer_jozsef_name_variants_and_verified_email_are_hard_suppressed():
    by_name = decision(contact_name="József Turczer", email="masik@example.hu")
    by_email = decision(email="turczer.jozsef@gmail.com", company_name="Ismeretlen")

    assert not by_name.allowed and by_name.status == OWNER_HARD_SUPPRESSION
    assert not by_email.allowed and by_email.status == OWNER_HARD_SUPPRESSION


def test_verified_gdn_network_domain_and_affiliation_are_hard_suppressed():
    by_domain = decision(email="iroda@pest.gdn-ingatlan.hu")
    by_affiliation = decision(
        email="partner@example.hu",
        organization_affiliations=("GDN Ingatlanhálózat",),
    )

    assert not by_domain.allowed and by_domain.status == OWNER_HARD_SUPPRESSION
    assert not by_affiliation.allowed and by_affiliation.status == OWNER_HARD_SUPPRESSION


def test_gdn_staff_affiliation_in_contact_name_is_hard_suppressed():
    result = decision(
        email="ertekesito@gmail.com",
        contact_name="Kovács Péter – GDN Ingatlanhálózat",
    )

    assert not result.allowed and result.status == OWNER_HARD_SUPPRESSION


def test_unverified_gdn_like_domain_or_unrelated_word_does_not_false_positive():
    unverified_domain = decision(email="iroda@gdn.hu", company_name="Minta Kft.")
    unrelated_word = decision(email="info@example.hu", company_name="Gdansk Építő Kft.")

    assert unverified_domain.allowed and unverified_domain.status == ALLOWED
    assert unrelated_word.allowed and unrelated_word.status == ALLOWED


def test_oc_budapest_blocked_offices_are_hard_suppressed():
    by_inbox = decision(email="mompark@oc.hu")
    by_affiliation = decision(
        email="iroda@example.hu",
        company_name="Otthon Centrum",
        office_affiliations=("Budapest II-A. kerület Hidegkúti út",),
    )

    assert not by_inbox.allowed and by_inbox.status == OWNER_HARD_SUPPRESSION
    assert not by_affiliation.allowed and by_affiliation.status == OWNER_HARD_SUPPRESSION


def test_oc_blocked_office_in_contact_affiliation_is_hard_suppressed():
    result = decision(
        email="kozvetito@gmail.com",
        contact_name="Kovács Anna – Otthon Centrum MOM Park",
    )

    assert not result.allowed and result.status == OWNER_HARD_SUPPRESSION


def test_oc_district_inflections_and_common_abbreviations_are_hard_suppressed():
    values = (
        "Otthon Centrum Budapest II. kerületi iroda",
        "Otthon Centrum II/A kerület",
        "Otthon Centrum 2. ker.",
        "Otthon Centrum XII. kerületi iroda",
        "Otthon Centrum 12. ker.",
    )

    for company_name in values:
        result = decision(email="partner@example.hu", company_name=company_name)
        assert not result.allowed and result.status == OWNER_HARD_SUPPRESSION


def test_unknown_oc_hu_address_is_fail_closed_review_not_network_wide_hard_ban():
    result = decision(email="ismeretlen@oc.hu")

    assert not result.allowed
    assert result.status == SUPPRESSION_REVIEW
    assert result.status != OWNER_HARD_SUPPRESSION


def test_verified_public_procurement_authority_is_blocked_for_outreach():
    by_flag = decision(
        email="beszerzes@example.hu",
        company_name="Minta szervezet",
        contracting_authority_verified=True,
        purpose="supplier",
    )
    by_name = decision(
        email="iroda@example.hu",
        company_name="Minta Város Önkormányzata",
        purpose="partner",
    )
    by_domain = decision(email="beszerzes@hivatal.gov.hu", purpose="sales")

    assert by_flag.status == PUBLIC_AUTHORITY_HARD_SUPPRESSION
    assert by_name.status == PUBLIC_AUTHORITY_HARD_SUPPRESSION
    assert by_domain.status == PUBLIC_AUTHORITY_HARD_SUPPRESSION


def test_suspected_contracting_authority_is_fail_closed_review():
    result = decision(
        email="iroda@example.hu",
        company_name="Nem tisztázott szervezet",
        contracting_authority_suspected=True,
        purpose="outreach",
    )

    assert not result.allowed and result.status == SUPPRESSION_REVIEW


def test_private_main_contractor_is_not_blocked_by_public_project_evidence_url():
    result = decision(
        email="ajanlat@maganfovallalkozo.hu",
        company_name="Magán Fővállalkozó Kft.",
        organization_class="private_contractor",
        evidence_url="https://kozbeszerzes.varos.gov.hu/tender/123",
        purpose="supplier",
    )

    assert result.allowed and result.status == ALLOWED


def test_public_entity_prefixes_do_not_block_unrelated_private_company_names():
    for company_name in ("Egyetemes Építő Kft.", "Hatóságtechnika Kft."):
        result = decision(
            email="info@example.hu",
            company_name=company_name,
            purpose="outreach",
        )
        assert result.allowed and result.status == ALLOWED


def test_project_evidence_url_does_not_create_gdn_recipient_affiliation():
    result = decision(
        email="partner@example.hu",
        company_name="Független Közvetítő Kft.",
        evidence_url="https://gdn-ingatlan.hu/ingatlan/123",
    )

    assert result.allowed and result.status == ALLOWED
