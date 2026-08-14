from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import (
    BookingRecord,
    BookingExperienceVersion,
    BookingSlot,
    CalendarEntry,
    CustomerPortalAccess,
    EventRecord,
    IntentDeclarationRecord,
    OutboxMessage,
    ProjectObjectState,
    ReservationPaymentRecord,
    ReservationOfferVersion,
    ReservationRecord,
    TaskRecord,
)


PASSWORD = "Imperial2026!"


def login(client, role: str) -> None:
    email = "owner@imperial.local" if role == "owner" else f"{role}@imperial.local"
    response = client.post("/login", data={"email": email, "password": PASSWORD}, follow_redirects=False)
    assert response.status_code == 303


def active_experience(client, *, booking_type: str = "online", days: int = 5) -> str:
    response = client.post(
        "/api/sales-commercial/experiences",
        json={
            "experience_id": f"BEXP-IMPERIAL-{booking_type.upper()}",
            "brand_id": "imperial-holding",
            "version": f"v1-{booking_type}",
            "display_name": "Imperial mérnöki konzultáció",
            "cta_label": "Időpontot foglalok",
            "trust_copy": "Mérnöki következő lépés és dokumentált projektút.",
            "confirmation_copy": "A foglalás a külső naptár visszaigazolása után végleges.",
            "theme_key": "imperial-engineering",
            "active": True,
        },
    )
    assert response.status_code == 200, response.text
    start = (datetime.now(UTC) + timedelta(days=days)).replace(hour=9, minute=0, second=0, microsecond=0)
    slot = client.post(
        "/api/sales-commercial/slots",
        json={
            "experience_id": response.json()["experience_id"],
            "booking_type": booking_type,
            "calendar_resource_id": f"sales-{booking_type}",
            "advisor_email": "sales@imperial.local",
            "starts_at": start.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
            "location": None if booking_type == "online" else "Imperial iroda",
        },
    )
    assert slot.status_code == 200, slot.text
    return slot.json()["slot_id"]


def booking_payload(slot_id: str, **overrides):
    return {
        "slot_id": slot_id,
        "lead_id": "LEAD-BOOKING-001",
        "customer_name": "Teszt Elek",
        "customer_email": "teszt.elek@example.com",
        "customer_phone": "+36 30 123 4567",
        "project_description": "Családi ház tervezése és kivitelezése Budapest környékén.",
        "plot_status": "keresés alatt",
        "planned_start": "6–12 hónap",
        "consent_version_id": "CONSENT-BOOKING-V1",
        "consent": True,
        **overrides,
    }


def active_offer(client, *, offer_id: str = "OFF-IMPERIAL-2026-01", amount: str = "790000", brand_id: str = "imperial-holding", intent_enabled: bool = False) -> str:
    now = datetime.now(UTC)
    response = client.post(
        "/api/sales-commercial/offers",
        json={
            "offer_version_id": offer_id,
            "brand_id": brand_id,
            "public_name": "Imperial ÁrGarancia Lekötés",
            "cta_label": "Lekötöm a kiválasztott házat",
            "reservation_amount_huf": amount,
            "target_start_months_min": 6,
            "target_start_months_max": 12,
            "price_lock_months": 12,
            "price_snapshot_id": "PS-IMPERIAL-126-V3",
            "terms_version_id": "TERMS-IMPERIAL-RSV-V2",
            "technical_scope_version_id": "SCOPE-IMPERIAL-126-KK-V4",
            "valid_from": (now - timedelta(days=1)).isoformat(),
            "valid_to": (now + timedelta(days=90)).isoformat(),
            "public_summary": "A kiválasztott ház jóváhagyott alapára és műszaki csomagja.",
            "exclusions_summary": "Telekfüggő tételek és ügyfélmódosítások nem automatikusan garantáltak.",
            "refund_rule": "A jóváhagyott TermsVersion szerinti visszatérítési szabály.",
            "transfer_rule": "Azonos ársávú Imperial házra egyszer átvihető.",
            "intent_declaration_enabled": intent_enabled,
            "intent_valid_days": 30,
            "intent_public_summary": "Fizetés nélküli, ellenőrzött Prefab szerződés-előkészítési szándék.",
            "legal_approved": True,
            "finance_approved": True,
            "pricing_approved": True,
            "active": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["offer_version_id"]


def reservation_payload(offer_id: str, **overrides):
    return {
        "lead_id": "LEAD-RSV-001",
        "offer_version_id": offer_id,
        "house_plan_id": "HOUSE-IMPERIAL-126",
        "house_config_id": "CFG-IMPERIAL-126-KK",
        "customer_name": "Árgarancia Ügyfél",
        "customer_email": "ar.garancia@example.com",
        "billing_name": "Árgarancia Ügyfél",
        "billing_address": "1111 Budapest, Próba utca 1.",
        "terms_accepted": True,
        **overrides,
    }


def intent_payload(offer_id: str, **overrides):
    return {
        "lead_id": "LEAD-INT-001",
        "offer_version_id": offer_id,
        "house_plan_id": "HOUSE-PREFAB-126",
        "house_config_id": "CFG-PREFAB-126-TECH",
        "customer_name": "Prefab Ügyfél",
        "customer_email": "customer@imperial.local",
        "customer_phone": "+36 30 555 0101",
        "target_start_window": "6–12 hónap",
        "project_scope": "Előregyártott szerkezetű családi ház műszaki és gyártási előkészítése.",
        "plot_status": "telek megvan",
        "consent_version_id": "CONSENT-INTENT-V1",
        "terms_accepted": True,
        "consent": True,
        **overrides,
    }


def test_booking_fail_closed_confirmation_and_double_booking(client, db):
    login(client, "owner")
    slot_id = active_experience(client)
    client.post("/logout")
    login(client, "sales")

    created = client.post("/api/sales-commercial/bookings", json=booking_payload(slot_id))
    assert created.status_code == 200, created.text
    booking_id = created.json()["booking_id"]
    assert created.json()["status"] == "calendar_locked"
    assert created.json()["external_sync_status"] == "pending"

    duplicate = client.post("/api/sales-commercial/bookings", json=booking_payload(slot_id, customer_email="other@example.com"))
    assert duplicate.status_code == 409

    missing_meet = client.post(f"/api/sales-commercial/bookings/{booking_id}/calendar-sync", json={"success": True, "calendar_event_id": "gcal-001"})
    assert missing_meet.status_code == 409
    confirmed = client.post(f"/api/sales-commercial/bookings/{booking_id}/calendar-sync", json={"success": True, "calendar_event_id": "gcal-001", "meeting_link": "https://meet.google.com/test-room"})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    db.expire_all()
    booking = db.scalar(select(BookingRecord).where(BookingRecord.booking_id == booking_id))
    slot = db.scalar(select(BookingSlot).where(BookingSlot.slot_id == slot_id))
    calendar = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == booking.calendar_entry_id))
    assert slot.status == "booked"
    assert calendar.status == "confirmed"
    assert db.scalar(select(EventRecord).where(EventRecord.object_id == booking_id, EventRecord.event_type == "BOOKING_CONFIRMED"))
    assert db.scalar(select(OutboxMessage).where(OutboxMessage.source_event_id.in_(select(EventRecord.event_id).where(EventRecord.object_id == booking_id))))


def test_site_visit_requires_full_address(client):
    login(client, "owner")
    slot_id = active_experience(client, booking_type="site_visit", days=7)
    client.post("/logout")
    login(client, "sales")
    blocked = client.post("/api/sales-commercial/bookings", json=booking_payload(slot_id))
    assert blocked.status_code == 409
    ok = client.post("/api/sales-commercial/bookings", json=booking_payload(slot_id, postal_code="2100", city="Gödöllő", street_address="Teszt utca 2.", access_notes="A kapu bal oldalán lehet behajtani."))
    assert ok.status_code == 200, ok.text


def test_offer_activation_and_successful_payment_activate_price_lock(client, db):
    login(client, "owner")
    offer_id = active_offer(client)
    client.post("/logout")
    login(client, "sales")
    created = client.post("/api/sales-commercial/reservations", json=reservation_payload(offer_id))
    assert created.status_code == 200, created.text
    reservation_id = created.json()["reservation_id"]
    assert created.json()["price_lock_status"] == "inactive"
    client.post("/logout")
    login(client, "owner")
    payment = client.post(
        f"/api/sales-commercial/reservations/{reservation_id}/payment",
        json={
            "provider": "sandbox-provider",
            "provider_reference": "txn-success-001",
            "idempotency_key": "idem-success-001",
            "amount_huf": "790000",
            "status": "succeeded",
            "evidence_url": "https://payments.example.test/evidence/txn-success-001",
        },
    )
    assert payment.status_code == 200, payment.text
    assert payment.json()["reservation"]["status"] == "price_lock_active"
    assert payment.json()["reservation"]["price_lock_status"] == "active"

    replay = client.post(f"/api/sales-commercial/reservations/{reservation_id}/payment", json={"provider": "sandbox-provider", "provider_reference": "txn-success-001", "idempotency_key": "idem-success-001", "amount_huf": "790000", "status": "succeeded", "evidence_url": "https://payments.example.test/evidence/txn-success-001"})
    assert replay.status_code == 200
    assert replay.json()["payment_id"] == payment.json()["payment_id"]

    db.expire_all()
    row = db.scalar(select(ReservationRecord).where(ReservationRecord.reservation_id == reservation_id))
    assert row.price_lock_expires_at is not None
    assert db.scalar(select(ReservationPaymentRecord).where(ReservationPaymentRecord.reservation_id == reservation_id))
    assert len(db.scalars(select(TaskRecord).where(TaskRecord.project_id == row.project_id, TaskRecord.task_id.like("TASK-RSV-%"))).all()) == 3
    destinations = {m.destination_module for m in db.scalars(select(OutboxMessage).join(EventRecord, EventRecord.event_id == OutboxMessage.source_event_id).where(EventRecord.object_id == reservation_id, EventRecord.event_type == "RESERVATION_ACTIVATED")).all()}
    assert {"crm", "financial-control", "contract-generator", "my-imperial", "plotcheck", "buildconfig"} <= destinations


def test_failed_or_mismatched_payment_never_activates_price_lock(client, db):
    login(client, "owner")
    offer_id = active_offer(client, offer_id="OFF-IMPERIAL-FAIL", amount="500000")
    created = client.post("/api/sales-commercial/reservations", json=reservation_payload(offer_id, customer_email="failed@example.com", house_config_id="CFG-FAIL"))
    reservation_id = created.json()["reservation_id"]
    mismatch = client.post(f"/api/sales-commercial/reservations/{reservation_id}/payment", json={"provider": "sandbox", "provider_reference": "txn-wrong", "idempotency_key": "idem-wrong", "amount_huf": "499999", "status": "succeeded", "evidence_url": "https://payments.example.test/wrong"})
    assert mismatch.status_code == 409
    failed = client.post(f"/api/sales-commercial/reservations/{reservation_id}/payment", json={"provider": "sandbox", "provider_reference": "txn-failed", "idempotency_key": "idem-failed", "amount_huf": "500000", "status": "failed"})
    assert failed.status_code == 200
    assert failed.json()["reservation"]["status"] == "payment_failed"
    assert failed.json()["reservation"]["price_lock_status"] == "inactive"
    db.expire_all()
    assert db.scalar(select(ReservationRecord).where(ReservationRecord.reservation_id == reservation_id)).price_lock_expires_at is None


def test_contract_conversion_requires_signed_contract_same_project(client, db):
    login(client, "owner")
    offer_id = active_offer(client, offer_id="OFF-IMPERIAL-CONVERT")
    created = client.post("/api/sales-commercial/reservations", json=reservation_payload(offer_id, customer_email="convert@example.com", house_config_id="CFG-CONVERT"))
    reservation_id = created.json()["reservation_id"]
    project_id = created.json()["project_id"]
    paid = client.post(f"/api/sales-commercial/reservations/{reservation_id}/payment", json={"provider": "sandbox", "provider_reference": "txn-convert", "idempotency_key": "idem-convert", "amount_huf": "790000", "status": "succeeded", "evidence_url": "https://payments.example.test/convert"})
    assert paid.status_code == 200
    blocked = client.post(f"/api/sales-commercial/reservations/{reservation_id}/convert", json={"contract_id": "CON-001"})
    assert blocked.status_code == 409
    db.add(ProjectObjectState(project_id=project_id, source_module="contract_generator", object_type="Contract", object_id="CON-001", status="signed", summary="Aláírt szerződés", payload_json="{}"))
    db.commit()
    converted = client.post(f"/api/sales-commercial/reservations/{reservation_id}/convert", json={"contract_id": "CON-001"})
    assert converted.status_code == 200, converted.text
    assert converted.json()["status"] == "converted"
    assert converted.json()["contract_id"] == "CON-001"


def test_sales_commercial_ui_and_role_access(client):
    login(client, "sales")
    page = client.get("/sales-commercial")
    assert page.status_code == 200
    assert "Foglalás és Árgarancia" in page.text
    assert "Booking Engine" in page.text
    assert "Reservation &amp; Price Lock" in page.text
    client.post("/logout")
    login(client, "project-manager")
    assert client.get("/sales-commercial").status_code == 403


def test_public_booking_and_reservation_screens_are_scoped(client):
    login(client, "owner")
    slot_id = active_experience(client, booking_type="personal", days=9)
    experience_id = "BEXP-IMPERIAL-PERSONAL"
    offer_id = active_offer(client, offer_id="OFF-IMPERIAL-PUBLIC")
    client.post("/logout")

    page = client.get(f"/booking/{experience_id}")
    assert page.status_code == 200
    assert "Imperial mérnöki konzultáció" in page.text
    created = client.post(f"/booking/{experience_id}", data={**booking_payload(slot_id), "consent": "on"})
    assert created.status_code == 200, created.text
    assert "Az idősávot zároltuk" in created.text
    assert "még nem CONFIRMED" in created.text

    offer_page = client.get(f"/reservation/{offer_id}")
    assert offer_page.status_code == 200
    assert "A ReservationID létrejötte nem aktív árgarancia" not in offer_page.text
    reservation = client.post(f"/reservation/{offer_id}", data={**reservation_payload(offer_id), "terms_accepted": "on"})
    assert reservation.status_code == 200, reservation.text
    assert "A ReservationID létrejötte nem aktív árgarancia" in reservation.text

    login(client, "customer")
    assert client.get("/sales-commercial").status_code == 403
    assert client.get("/api/sales-commercial/summary").status_code == 403


def test_version_rotation_is_atomic_and_auditable(client, db):
    login(client, "owner")
    active_experience(client, booking_type="online", days=11)
    second = client.post("/api/sales-commercial/experiences", json={"experience_id": "BEXP-IMPERIAL-ONLINE-V2", "brand_id": "imperial-holding", "version": "v2-online", "display_name": "Imperial konzultáció v2", "cta_label": "Konzultációt kérek", "trust_copy": "Új, jóváhagyott mérnöki ügyfélút.", "confirmation_copy": "Külső naptárig nem végleges.", "theme_key": "imperial-v2", "active": False})
    assert second.status_code == 200
    rotated = client.post("/api/sales-commercial/experiences/BEXP-IMPERIAL-ONLINE-V2/activation", json={"active": True, "note": "Tulajdonosi v2 release"})
    assert rotated.status_code == 200
    db.expire_all()
    experiences = db.scalars(select(BookingExperienceVersion).where(BookingExperienceVersion.brand_id == "imperial-holding")).all()
    assert sum(1 for row in experiences if row.active) == 1
    assert next(row for row in experiences if row.active).experience_id == "BEXP-IMPERIAL-ONLINE-V2"

    active_offer(client, offer_id="OFF-ROTATE-V1")
    now = datetime.now(UTC)
    draft = client.post("/api/sales-commercial/offers", json={"offer_version_id": "OFF-ROTATE-V2", "brand_id": "imperial-holding", "public_name": "Imperial ÁrGarancia v2", "cta_label": "Lekötöm", "reservation_amount_huf": "790000", "target_start_months_min": 6, "target_start_months_max": 12, "price_lock_months": 12, "price_snapshot_id": "PS-V2", "terms_version_id": "TERMS-V2", "technical_scope_version_id": "SCOPE-V2", "valid_from": (now - timedelta(days=1)).isoformat(), "valid_to": (now + timedelta(days=60)).isoformat(), "public_summary": "Aktuális ház- és csomagár.", "exclusions_summary": "Telekfüggő tételek kizárva.", "refund_rule": "Terms V2 szerint.", "transfer_rule": "Terms V2 szerint.", "legal_approved": True, "finance_approved": True, "pricing_approved": True, "active": False})
    assert draft.status_code == 200, draft.text
    activated = client.post("/api/sales-commercial/offers/OFF-ROTATE-V2/activation", json={"active": True, "note": "Tulajdonosi offer release"})
    assert activated.status_code == 200, activated.text
    db.expire_all()
    offers = db.scalars(select(ReservationOfferVersion).where(ReservationOfferVersion.brand_id == "imperial-holding")).all()
    assert sum(1 for row in offers if row.active) == 1
    assert next(row for row in offers if row.active).offer_version_id == "OFF-ROTATE-V2"
    assert client.get("/sales-commercial").status_code == 200


def test_prefab_intent_is_separate_from_payment_and_creates_myimperial_access(client, db):
    login(client, "owner")
    offer_id = active_offer(client, offer_id="OFF-PREFAB-INTENT", amount="500000", brand_id="prefab", intent_enabled=True)
    created = client.post("/api/sales-commercial/intents", json=intent_payload(offer_id))
    assert created.status_code == 200, created.text
    data = created.json()
    assert data["status"] == "submitted"
    assert data["price_snapshot_id"] == "PS-IMPERIAL-126-V3"
    assert data["terms_version_id"] == "TERMS-IMPERIAL-RSV-V2"
    assert "payment_id" not in data

    db.expire_all()
    row = db.scalar(select(IntentDeclarationRecord).where(IntentDeclarationRecord.intent_declaration_id == data["intent_declaration_id"]))
    assert row is not None
    assert db.scalar(select(CustomerPortalAccess).where(CustomerPortalAccess.project_id == row.project_id, CustomerPortalAccess.customer_email == "customer@imperial.local"))
    assert db.scalar(select(ReservationPaymentRecord).where(ReservationPaymentRecord.reservation_id == row.intent_declaration_id)) is None
    destinations = {m.destination_module for m in db.scalars(select(OutboxMessage).join(EventRecord, EventRecord.event_id == OutboxMessage.source_event_id).where(EventRecord.object_id == row.intent_declaration_id, EventRecord.event_type == "INTENT_DECLARATION_SUBMITTED")).all()}
    assert {"crm", "contract-generator", "my-imperial", "buildconfig"} <= destinations


def test_intent_review_requires_delivery_evidence_and_signed_contract(client, db):
    login(client, "owner")
    offer_id = active_offer(client, offer_id="OFF-PREFAB-REVIEW", brand_id="prefab", intent_enabled=True)
    created = client.post("/api/sales-commercial/intents", json=intent_payload(offer_id, customer_email="review.intent@example.com", house_config_id="CFG-PREFAB-REVIEW"))
    intent_id = created.json()["intent_declaration_id"]
    project_id = created.json()["project_id"]

    blocked = client.post(f"/api/sales-commercial/intents/{intent_id}/review", json={"action": "approve", "note": "Minden verzió egyezik."})
    assert blocked.status_code == 409
    approved = client.post(f"/api/sales-commercial/intents/{intent_id}/review", json={"action": "approve", "note": "Minden verzió és ügyfélelfogadás egyezik.", "delivery_evidence_url": "https://evidence.example.test/intent/review"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    no_contract = client.post(f"/api/sales-commercial/intents/{intent_id}/convert", json={"contract_id": "CON-PREFAB-001"})
    assert no_contract.status_code == 409
    db.add(ProjectObjectState(project_id=project_id, source_module="contract_generator", object_type="Contract", object_id="CON-PREFAB-001", status="signed", summary="Aláírt Prefab szerződés", payload_json="{}"))
    db.commit()
    converted = client.post(f"/api/sales-commercial/intents/{intent_id}/convert", json={"contract_id": "CON-PREFAB-001"})
    assert converted.status_code == 200, converted.text
    assert converted.json()["status"] == "converted"


def test_intent_change_request_can_be_resubmitted_from_public_management(client, db):
    login(client, "owner")
    offer_id = active_offer(client, offer_id="OFF-PREFAB-CHANGES", brand_id="prefab", intent_enabled=True)
    created = client.post("/api/sales-commercial/intents", json=intent_payload(offer_id, customer_email="changes@example.com", house_config_id="CFG-PREFAB-CHANGES"))
    intent_id = created.json()["intent_declaration_id"]
    requested = client.post(f"/api/sales-commercial/intents/{intent_id}/review", json={"action": "request_changes", "note": "Pontosítsa a telek státuszát és a műszaki csomagot."})
    assert requested.status_code == 200
    db.expire_all()
    row = db.scalar(select(IntentDeclarationRecord).where(IntentDeclarationRecord.intent_declaration_id == intent_id))
    managed = client.post(f"/intent/manage/{row.cancellation_token}/resubmit", data={"house_plan_id": row.house_plan_id, "house_config_id": row.house_config_id, "customer_phone": row.customer_phone, "target_start_window": "8–14 hónap", "project_scope": "Pontosított gyártási scope, telekadottságok és műszaki csomag részletesen.", "plot_status": "telek tulajdonban", "consent": "on"})
    assert managed.status_code == 200, managed.text
    assert "újra beküldtük" in managed.text
    db.expire_all()
    assert db.scalar(select(IntentDeclarationRecord).where(IntentDeclarationRecord.intent_declaration_id == intent_id)).status == "submitted"


def test_myimperial_customer_isolation_and_public_intent_screen(client):
    login(client, "owner")
    offer_id = active_offer(client, offer_id="OFF-PREFAB-PORTAL", brand_id="prefab", intent_enabled=True)
    public_page = client.get(f"/intent/{offer_id}")
    assert public_page.status_code == 200
    assert "nem fizetett lekötés" in public_page.text
    created = client.post("/api/sales-commercial/intents", json=intent_payload(offer_id, customer_email="customer@imperial.local", house_config_id="CFG-PREFAB-PORTAL"))
    assert created.status_code == 200
    client.post("/logout")
    login(client, "customer")
    portal = client.get("/my-imperial")
    assert portal.status_code == 200
    assert created.json()["intent_declaration_id"] in portal.text
    summary = client.get("/api/my-imperial/summary")
    assert summary.status_code == 200
    assert all(row["project_id"] == created.json()["project_id"] for row in summary.json()["projects"])
