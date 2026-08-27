from sqlalchemy import select

from app.models import DevelopmentDiscoveryRecord
from app.seed import DEMO_PASSWORD


PASSWORD = DEMO_PASSWORD


def login(client, role: str):
    email = "owner@imperial.local" if role == "owner" else f"{role}@imperial.local"
    response = client.post(
        "/login",
        data={"email": email, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def logout(client):
    assert client.post("/logout", follow_redirects=False).status_code == 303


def discovery_form(discovery_id: str, *, decision: str = "integrate") -> dict[str, str]:
    is_exception = decision == "new_exception"
    return {
        "discovery_id": discovery_id,
        "requested_capability": "Központi döntési munkafolyamat bővítése",
        "requested_module_key": "governance-workspace-ui",
        "canonical_module_key": "" if is_exception else "crm",
        "decision": decision,
        "source_version": "1.0.0",
        "searched_terms": "governance, döntés, audit",
        "implementation_gap": "A meglévő kanonikus modulhoz hitelesített felhasználói döntési képernyő szükséges.",
        "exception_reason": "Új, kanonikus modul hiányában elkülönített kivétel szükséges." if is_exception else "",
    }


def test_governance_ui_enforces_four_eyes_and_immutable_review(client, db):
    login(client, "platform-admin")
    created = client.post(
        "/development-governance",
        data=discovery_form("DISC-UI-FOUR-EYES"),
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    row = db.scalar(
        select(DevelopmentDiscoveryRecord).where(
            DevelopmentDiscoveryRecord.discovery_id == "DISC-UI-FOUR-EYES"
        )
    )
    assert row is not None
    assert row.status == "pending_review"
    assert row.requested_by == "platform-admin@imperial.local"

    own_review = client.post(
        f"/development-governance/{row.discovery_id}/review",
        data={"status": "approved", "review_note": "A kanonikus újrafelhasználás igazolt."},
    )
    assert own_review.status_code == 409

    logout(client)
    login(client, "owner")
    approved = client.post(
        f"/development-governance/{row.discovery_id}/review",
        data={"status": "approved", "review_note": "A CRM kanonikus marad, csak a döntési felület bővül."},
        follow_redirects=False,
    )
    assert approved.status_code == 303, approved.text
    db.refresh(row)
    assert row.status == "approved"
    assert row.reviewed_by == "owner@imperial.local"
    assert row.review_note == "A CRM kanonikus marad, csak a döntési felület bővül."

    repeated = client.post(
        f"/development-governance/{row.discovery_id}/review",
        data={"status": "rejected", "review_note": "Utólagos átírás nem megengedett."},
    )
    assert repeated.status_code == 409


def test_new_exception_requires_explicit_owner_approval(client, db):
    login(client, "platform-admin")
    created = client.post(
        "/development-governance",
        data=discovery_form("DISC-UI-EXCEPTION", decision="new_exception"),
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    logout(client)
    login(client, "owner")

    missing_exception_gate = client.post(
        "/development-governance/DISC-UI-EXCEPTION/review",
        data={"status": "approved", "review_note": "A kivételi döntés szakmailag indokolt."},
    )
    assert missing_exception_gate.status_code == 409

    approved = client.post(
        "/development-governance/DISC-UI-EXCEPTION/review",
        data={
            "status": "approved",
            "exception_approved": "on",
            "review_note": "Tulajdonosként a dokumentált kivételt kifejezetten jóváhagyom.",
        },
        follow_redirects=False,
    )
    assert approved.status_code == 303, approved.text
    row = db.scalar(
        select(DevelopmentDiscoveryRecord).where(
            DevelopmentDiscoveryRecord.discovery_id == "DISC-UI-EXCEPTION"
        )
    )
    assert row.status == "approved"
    assert row.exception_approved is True


def test_governance_decision_is_not_available_to_customer(client):
    login(client, "customer")
    denied = client.post(
        "/development-governance/DISC-CANON-CRM/review",
        data={"status": "approved", "review_note": "Jogosulatlan döntési kísérlet."},
    )
    assert denied.status_code == 403
