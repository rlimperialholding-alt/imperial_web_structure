from app.services.crm_transport import crm_service_headers


def test_private_sites_transport_keeps_service_and_access_credentials_separate():
    headers = crm_service_headers(
        "X-Platform-CRM-Token",
        "service-secret",
        content_type="application/json",
        bypass_token="sites-access-secret",
    )

    assert headers == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Platform-CRM-Token": "service-secret",
        "OAI-Sites-Authorization": "Bearer sites-access-secret",
    }


def test_public_or_local_crm_transport_does_not_invent_authorization():
    headers = crm_service_headers(
        "X-ITEP-CRM-Token",
        "read-secret",
        bypass_token="",
    )

    assert headers == {
        "Accept": "application/json",
        "X-ITEP-CRM-Token": "read-secret",
    }
