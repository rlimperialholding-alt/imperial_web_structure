from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import (
    BookingExperienceVersion,
    BookingRecord,
    BookingSlot,
    CalendarEntry,
    CustomerPortalAccess,
    IntentDeclarationRecord,
    ProjectObjectState,
    ProjectRegistry,
    ReservationOfferVersion,
    ReservationPaymentRecord,
    ReservationRecord,
    TaskRecord,
)
from ..schemas import (
    BookingCalendarSyncIn,
    BookingCreateIn,
    BookingExperienceIn,
    BookingOutcomeIn,
    BookingRescheduleIn,
    BookingSlotIn,
    EventIn,
    IntentDeclarationCreateIn,
    IntentDeclarationReviewIn,
    IntentDeclarationUpdateIn,
    ReservationCreateIn,
    ReservationLifecycleIn,
    ReservationOfferIn,
    ReservationPaymentResultIn,
    VersionActivationIn,
)
from .integration import ingest_event


BOOKING_ACTIVE = {"calendar_locked", "confirmed", "reminded"}
RESERVATION_ACTIVE = {"payment_pending", "reservation_activated", "price_lock_active"}
INTENT_ACTIVE = {"submitted", "changes_requested", "approved", "contract_preparation"}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _ensure_journey_project(
    db: Session,
    project_id: str | None,
    *,
    customer_name: str,
    responsible: str | None,
) -> str:
    journey_id = project_id or _new_id("JRN")
    row = db.scalar(select(ProjectRegistry).where(ProjectRegistry.project_id == journey_id))
    if not row:
        db.add(
            ProjectRegistry(
                project_id=journey_id,
                name=f"Értékesítési ügyfélút – {customer_name}",
                customer_name=customer_name,
                project_type="sales_journey",
                status="pre_contract",
                responsible=responsible,
                next_action="Kvalifikáció és következő értékesítési lépés rögzítése.",
            )
        )
        db.flush()
    return journey_id


def _ensure_customer_portal_access(
    db: Session,
    *,
    project_id: str,
    customer_email: str,
    contact_name: str,
    source_type: str,
    source_id: str,
    actor: str,
) -> CustomerPortalAccess:
    normalized_email = customer_email.strip().lower()
    row = db.scalar(
        select(CustomerPortalAccess).where(
            CustomerPortalAccess.project_id == project_id,
            CustomerPortalAccess.customer_email == normalized_email,
        )
    )
    if row:
        row.active = True
        row.contact_name = contact_name
        return row
    row = CustomerPortalAccess(
        access_id=_new_id("MIA"),
        project_id=project_id,
        customer_email=normalized_email,
        contact_name=contact_name,
        source_type=source_type,
        source_id=source_id,
        created_by=actor,
    )
    db.add(row)
    return row


def _emit(
    db: Session,
    *,
    project_id: str,
    source_module: str,
    event_type: str,
    object_type: str,
    object_id: str,
    status: str,
    summary: str,
    actor: str,
    responsible: str | None = None,
    financial_impact_huf: Decimal = Decimal("0"),
    route_to: list[str] | None = None,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    next_action: str | None = None,
) -> None:
    ingest_event(
        db,
        EventIn(
            event_id=_new_id("EVT"),
            dedupe_key=f"{source_module}:{object_id}:{event_type}:{status}",
            project_id=project_id,
            source_module=source_module,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            status=status,
            severity=severity,
            responsible=responsible,
            financial_impact_huf=financial_impact_huf,
            next_action=next_action,
            payload={"summary": summary, **(payload or {})},
            route_to=route_to or [],
        ),
        actor=actor,
    )
    # ingest_event is idempotent and returns without committing when the event
    # already exists. State changes and audit rows made before a replay still
    # have to be durable.
    db.commit()


def create_booking_experience(
    db: Session, data: BookingExperienceIn, *, actor: str
) -> BookingExperienceVersion:
    if db.scalar(
        select(BookingExperienceVersion).where(
            or_(
                BookingExperienceVersion.experience_id == data.experience_id,
                and_(
                    BookingExperienceVersion.brand_id == data.brand_id,
                    BookingExperienceVersion.version == data.version,
                ),
            )
        )
    ):
        raise ValueError("Ez a BookingExperienceVersion már létezik.")
    if data.active:
        active = db.scalar(
            select(BookingExperienceVersion).where(
                BookingExperienceVersion.brand_id == data.brand_id,
                BookingExperienceVersion.active.is_(True),
            )
        )
        if active:
            raise ValueError("A márkához már van aktív foglalási élményverzió.")
    row = BookingExperienceVersion(
        experience_id=data.experience_id,
        brand_id=data.brand_id,
        version=data.version,
        display_name=data.display_name,
        cta_label=data.cta_label,
        trust_copy=data.trust_copy,
        confirmation_copy=data.confirmation_copy,
        theme_key=data.theme_key,
        active=data.active,
        policy_json=json.dumps(data.policy, ensure_ascii=False),
        created_by=actor,
    )
    db.add(row)
    audit(db, actor=actor, action="booking_experience_created", entity_type="booking_experience", entity_id=row.experience_id, after=data.model_dump(mode="json"))
    db.commit()
    db.refresh(row)
    return row


def set_booking_experience_active(
    db: Session,
    experience_id: str,
    data: VersionActivationIn,
    *,
    actor: str,
) -> BookingExperienceVersion:
    row = db.scalar(
        select(BookingExperienceVersion).where(
            BookingExperienceVersion.experience_id == experience_id
        ).with_for_update()
    )
    if not row:
        raise KeyError(experience_id)
    if data.active:
        current = db.scalars(
            select(BookingExperienceVersion).where(
                BookingExperienceVersion.brand_id == row.brand_id,
                BookingExperienceVersion.active.is_(True),
                BookingExperienceVersion.experience_id != row.experience_id,
            )
        ).all()
        for old in current:
            old.active = False
    before = row.active
    row.active = data.active
    audit(db, actor=actor, action="booking_experience_activation_changed", entity_type="booking_experience", entity_id=row.experience_id, before={"active": before}, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def create_booking_slot(db: Session, data: BookingSlotIn, *, actor: str) -> BookingSlot:
    _release_expired_holds(db)
    experience = db.scalar(
        select(BookingExperienceVersion).where(
            BookingExperienceVersion.experience_id == data.experience_id
        )
    )
    if not experience:
        raise ValueError("Ismeretlen BookingExperienceVersion.")
    if _aware(data.ends_at) <= _aware(data.starts_at):
        raise ValueError("A foglalási idősáv vége a kezdete után kell legyen.")
    collision = db.scalar(
        select(BookingSlot).where(
            BookingSlot.calendar_resource_id == data.calendar_resource_id,
            BookingSlot.status.in_(["available", "held", "booked"]),
            BookingSlot.starts_at < data.ends_at,
            BookingSlot.ends_at > data.starts_at,
        )
    )
    if collision:
        raise ValueError(f"Az erőforrásnak átfedő idősávja van: {collision.slot_id}.")
    if data.booking_type in {"personal", "site_visit"} and not (data.location or "").strip():
        raise ValueError("Személyes konzultációhoz vagy helyszíni szemléhez helyszín kötelező.")
    row = BookingSlot(
        slot_id=_new_id("SLOT"),
        experience_id=data.experience_id,
        brand_id=experience.brand_id,
        booking_type=data.booking_type,
        calendar_resource_id=data.calendar_resource_id,
        advisor_email=data.advisor_email,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        location=data.location,
        created_by=actor,
    )
    db.add(row)
    audit(db, actor=actor, action="booking_slot_created", entity_type="booking_slot", entity_id=row.slot_id, after=data.model_dump(mode="json"))
    db.commit()
    db.refresh(row)
    return row


def _release_expired_holds(db: Session) -> int:
    rows = db.scalars(
        select(BookingSlot).where(
            BookingSlot.status == "held",
            BookingSlot.held_until.is_not(None),
            BookingSlot.held_until < utcnow(),
        )
    ).all()
    released = 0
    for slot in rows:
        booking = db.scalar(
            select(BookingRecord).where(
                BookingRecord.slot_id == slot.slot_id,
                BookingRecord.status == "calendar_locked",
            )
        )
        if booking:
            booking.status = "expired"
            booking.external_sync_status = "expired"
        slot.status = "available"
        slot.held_until = None
        released += 1
    if released:
        db.commit()
    return released


def create_booking(db: Session, data: BookingCreateIn, *, actor: str) -> BookingRecord:
    if not data.consent:
        raise ValueError("Adatkezelési hozzájárulás nélkül foglalás nem indítható.")
    _release_expired_holds(db)
    slot = db.scalar(
        select(BookingSlot).where(BookingSlot.slot_id == data.slot_id).with_for_update()
    )
    if not slot or slot.status != "available" or _aware(slot.starts_at) <= utcnow():
        raise ValueError("A kiválasztott idősáv már nem foglalható.")
    experience = db.scalar(
        select(BookingExperienceVersion).where(
            BookingExperienceVersion.experience_id == slot.experience_id,
            BookingExperienceVersion.active.is_(True),
        )
    )
    if not experience:
        raise ValueError("A márka foglalási élménye nincs aktív állapotban.")
    if slot.booking_type == "site_visit" and not all(
        (data.postal_code, data.city, data.street_address, data.access_notes)
    ):
        raise ValueError("Helyszíni szemléhez teljes cím és megközelíthetőségi információ kötelező.")
    duplicate = db.scalar(
        select(BookingRecord).where(
            BookingRecord.customer_email == data.customer_email,
            BookingRecord.slot_id == slot.slot_id,
            BookingRecord.status.in_(BOOKING_ACTIVE),
        )
    )
    if duplicate:
        return duplicate
    project_id = _ensure_journey_project(
        db,
        data.project_id,
        customer_name=data.customer_name,
        responsible=slot.advisor_email,
    )
    row = BookingRecord(
        booking_id=_new_id("BKG"),
        slot_id=slot.slot_id,
        project_id=project_id,
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
        brand_id=slot.brand_id,
        booking_type=slot.booking_type,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        customer_phone=data.customer_phone,
        project_description=data.project_description,
        plot_status=data.plot_status,
        planned_start=data.planned_start,
        postal_code=data.postal_code,
        city=data.city,
        street_address=data.street_address,
        access_notes=data.access_notes,
        document_url=data.document_url,
        consent_version_id=data.consent_version_id,
        consent_at=utcnow(),
        cancellation_token=secrets.token_urlsafe(32),
        attribution_json=json.dumps(data.attribution, ensure_ascii=False),
    )
    slot.status = "held"
    slot.held_until = utcnow() + timedelta(minutes=30)
    calendar = CalendarEntry(
        entry_id=_new_id("CAL"),
        project_id=project_id,
        entry_type="meeting" if slot.booking_type != "site_visit" else "inspection",
        title=f"{experience.display_name} – {data.customer_name}",
        description=data.project_description,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        assignee=slot.advisor_email,
        participants_json=json.dumps([data.customer_email], ensure_ascii=False),
        location=slot.location if slot.booking_type != "site_visit" else f"{data.postal_code} {data.city}, {data.street_address}",
        status="planned",
        priority="normal",
        source_module="booking-engine",
        source_object_id=row.booking_id,
        capacity_hours=Decimal(str((_aware(slot.ends_at) - _aware(slot.starts_at)).total_seconds() / 3600)),
        created_by=actor,
        updated_by=actor,
    )
    row.calendar_entry_id = calendar.entry_id
    db.add_all([row, calendar])
    db.flush()
    audit(db, actor=actor, action="booking_calendar_locked", entity_type="booking", entity_id=row.booking_id, after={"slot_id": slot.slot_id, "project_id": project_id, "consent_version_id": data.consent_version_id})
    _emit(
        db,
        project_id=project_id,
        source_module="booking-engine",
        event_type="BOOKING_FORM_COMPLETED",
        object_type="Booking",
        object_id=row.booking_id,
        status=row.status,
        summary="A foglalási űrlap teljes, a belső idősáv zárolva; külső naptár-visszaigazolás szükséges.",
        actor=actor,
        responsible=slot.advisor_email,
        route_to=["crm", "smart-calendar", "lead-intelligence"],
        payload={"lead_id": row.lead_id, "opportunity_id": row.opportunity_id, "brand_id": row.brand_id, "slot_id": slot.slot_id, "calendar_entry_id": calendar.entry_id, "external_confirmation": False},
    )
    db.refresh(row)
    return row


def record_booking_calendar_sync(
    db: Session, booking_id: str, data: BookingCalendarSyncIn, *, actor: str
) -> BookingRecord:
    row = db.scalar(
        select(BookingRecord).where(BookingRecord.booking_id == booking_id).with_for_update()
    )
    if not row:
        raise KeyError(booking_id)
    slot = db.scalar(select(BookingSlot).where(BookingSlot.slot_id == row.slot_id))
    if slot is None:
        raise KeyError(row.slot_id)
    calendar = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == row.calendar_entry_id))
    if data.success:
        if not (data.calendar_event_id or "").strip():
            raise ValueError("Sikeres szinkronhoz CalendarEventID kötelező.")
        if row.booking_type == "online" and not (data.meeting_link or "").strip():
            raise ValueError("Online konzultációhoz működő meeting-link kötelező.")
        row.status = "confirmed"
        row.external_sync_status = "succeeded"
        row.calendar_event_id = data.calendar_event_id
        row.meeting_link = data.meeting_link
        slot.status = "booked"
        slot.held_until = None
        if calendar:
            calendar.status = "confirmed"
            calendar.version += 1
            calendar.updated_by = actor
        event_type = "BOOKING_CONFIRMED"
        summary = "A külső naptár-esemény létrejött; a foglalás megerősített."
    else:
        row.status = "calendar_sync_failed"
        row.external_sync_status = "failed"
        event_type = "BOOKING_CALENDAR_SYNC_FAILED"
        summary = f"A foglalás nem lett megerősítve: {data.error or 'külső naptárhiba'}."
    row.version += 1
    audit(db, actor=actor, action="booking_calendar_sync_recorded", entity_type="booking", entity_id=row.booking_id, after=data.model_dump(mode="json"))
    _emit(
        db,
        project_id=row.project_id,
        source_module="booking-engine",
        event_type=event_type,
        object_type="Booking",
        object_id=row.booking_id,
        status=row.status,
        summary=summary,
        actor=actor,
        responsible=slot.advisor_email,
        route_to=["crm", "smart-calendar", "my-imperial"],
        payload={"calendar_event_id": row.calendar_event_id, "meeting_link": row.meeting_link, "external_sync_status": row.external_sync_status},
        severity="high" if not data.success else "info",
        next_action="A naptáradapter hibájának javítása és a foglalás újraszinkronizálása." if not data.success else None,
    )
    db.refresh(row)
    return row


def reschedule_booking(
    db: Session, booking_id: str, data: BookingRescheduleIn, *, actor: str
) -> BookingRecord:
    row = db.scalar(select(BookingRecord).where(BookingRecord.booking_id == booking_id).with_for_update())
    if not row:
        raise KeyError(booking_id)
    if row.status not in BOOKING_ACTIVE | {"calendar_sync_failed"}:
        raise ValueError("A foglalás ebben az állapotban nem ütemezhető át.")
    old_slot = db.scalar(select(BookingSlot).where(BookingSlot.slot_id == row.slot_id))
    new_slot = db.scalar(select(BookingSlot).where(BookingSlot.slot_id == data.new_slot_id).with_for_update())
    if old_slot is None:
        raise KeyError(row.slot_id)
    if not new_slot or new_slot.status != "available" or new_slot.brand_id != row.brand_id or new_slot.booking_type != row.booking_type:
        raise ValueError("Az új idősáv nem foglalható vagy nem kompatibilis.")
    old_slot.status = "available"
    old_slot.held_until = None
    new_slot.status = "held"
    new_slot.held_until = utcnow() + timedelta(minutes=30)
    row.slot_id = new_slot.slot_id
    row.status = "calendar_locked"
    row.external_sync_status = "pending"
    row.calendar_event_id = None
    row.meeting_link = None
    row.version += 1
    calendar = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == row.calendar_entry_id))
    if calendar:
        calendar.starts_at = new_slot.starts_at
        calendar.ends_at = new_slot.ends_at
        calendar.location = (
            f"{row.postal_code} {row.city}, {row.street_address}"
            if row.booking_type == "site_visit"
            else new_slot.location
        )
        calendar.status = "planned"
        calendar.version += 1
        calendar.updated_by = actor
    audit(db, actor=actor, action="booking_rescheduled", entity_type="booking", entity_id=row.booking_id, after={"old_slot_id": old_slot.slot_id, "new_slot_id": new_slot.slot_id, "reason": data.reason})
    _emit(db, project_id=row.project_id, source_module="booking-engine", event_type="BOOKING_RESCHEDULED", object_type="Booking", object_id=row.booking_id, status=row.status, summary="A foglalás új idősávba került; új külső naptár-visszaigazolás szükséges.", actor=actor, responsible=new_slot.advisor_email, route_to=["crm", "smart-calendar", "my-imperial"], payload={"old_slot_id": old_slot.slot_id, "new_slot_id": new_slot.slot_id, "reason": data.reason})
    db.refresh(row)
    return row


def cancel_booking(db: Session, booking_id: str, *, actor: str, reason: str) -> BookingRecord:
    row = db.scalar(select(BookingRecord).where(BookingRecord.booking_id == booking_id).with_for_update())
    if not row:
        raise KeyError(booking_id)
    if row.status in {"cancelled", "completed", "no_show", "expired"}:
        raise ValueError("A foglalás már lezárt állapotban van.")
    slot = db.scalar(select(BookingSlot).where(BookingSlot.slot_id == row.slot_id))
    if slot is None:
        raise KeyError(row.slot_id)
    slot.status = "available"
    slot.held_until = None
    row.status = "cancelled"
    row.version += 1
    calendar = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == row.calendar_entry_id))
    if calendar:
        calendar.status = "cancelled"
        calendar.version += 1
        calendar.updated_by = actor
    audit(db, actor=actor, action="booking_cancelled", entity_type="booking", entity_id=row.booking_id, after={"reason": reason})
    _emit(db, project_id=row.project_id, source_module="booking-engine", event_type="BOOKING_CANCELLED", object_type="Booking", object_id=row.booking_id, status=row.status, summary=f"A foglalás lemondva: {reason}", actor=actor, responsible=slot.advisor_email, route_to=["crm", "smart-calendar", "my-imperial"])
    db.refresh(row)
    return row


def update_booking_outcome(
    db: Session, booking_id: str, data: BookingOutcomeIn, *, actor: str
) -> BookingRecord:
    row = db.scalar(
        select(BookingRecord).where(BookingRecord.booking_id == booking_id).with_for_update()
    )
    if not row:
        raise KeyError(booking_id)
    allowed = {
        "confirmed": {"reminded", "completed", "no_show"},
        "reminded": {"completed", "no_show"},
    }
    if data.status not in allowed.get(row.status, set()):
        raise ValueError("A foglalás ebből az állapotból nem váltható a kért eredményre.")
    row.status = data.status
    row.version += 1
    calendar = db.scalar(select(CalendarEntry).where(CalendarEntry.entry_id == row.calendar_entry_id))
    if calendar and data.status in {"completed", "no_show"}:
        calendar.status = "completed"
        calendar.version += 1
        calendar.updated_by = actor
    audit(db, actor=actor, action=f"booking_{data.status}", entity_type="booking", entity_id=row.booking_id, after=data.model_dump())
    _emit(db, project_id=row.project_id, source_module="booking-engine", event_type=f"BOOKING_{data.status.upper()}", object_type="Booking", object_id=row.booking_id, status=row.status, summary=f"A foglalás eredménye: {data.status}. {data.note}", actor=actor, route_to=["crm", "smart-calendar", "lead-intelligence"], payload={"note": data.note})
    db.refresh(row)
    return row


def create_offer_version(db: Session, data: ReservationOfferIn, *, actor: str) -> ReservationOfferVersion:
    if db.scalar(select(ReservationOfferVersion).where(ReservationOfferVersion.offer_version_id == data.offer_version_id)):
        raise ValueError("Ez az OfferVersionID már létezik.")
    if _aware(data.valid_to) <= _aware(data.valid_from):
        raise ValueError("Az ajánlat érvényességi vége a kezdete után kell legyen.")
    if data.target_start_months_max < data.target_start_months_min:
        raise ValueError("A célindítás felső határa nem lehet kisebb az alsó határnál.")
    if data.active and not (data.legal_approved and data.finance_approved and data.pricing_approved):
        raise ValueError("Aktív ajánlathoz jogi, pénzügyi és árazási jóváhagyás is kötelező.")
    if data.intent_declaration_enabled and not data.intent_public_summary.strip():
        raise ValueError("Engedélyezett szándéknyilatkozati úthoz külön nyilvános összefoglaló kötelező.")
    if data.active:
        current = db.scalar(select(ReservationOfferVersion).where(ReservationOfferVersion.brand_id == data.brand_id, ReservationOfferVersion.active.is_(True)))
        if current:
            raise ValueError("A márkához már van aktív OfferVersion.")
    row = ReservationOfferVersion(**data.model_dump(), created_by=actor)
    db.add(row)
    audit(db, actor=actor, action="reservation_offer_created", entity_type="reservation_offer", entity_id=row.offer_version_id, after=data.model_dump(mode="json"))
    db.commit()
    db.refresh(row)
    return row


def set_offer_active(
    db: Session,
    offer_version_id: str,
    data: VersionActivationIn,
    *,
    actor: str,
) -> ReservationOfferVersion:
    row = db.scalar(
        select(ReservationOfferVersion).where(
            ReservationOfferVersion.offer_version_id == offer_version_id
        ).with_for_update()
    )
    if not row:
        raise KeyError(offer_version_id)
    if data.active:
        if not (row.legal_approved and row.finance_approved and row.pricing_approved):
            raise ValueError("Jogi, pénzügyi és árazási PASS nélkül az ajánlat nem aktiválható.")
        if not (_aware(row.valid_from) <= utcnow() <= _aware(row.valid_to)):
            raise ValueError("Csak aktuálisan érvényes OfferVersion aktiválható.")
        current = db.scalars(
            select(ReservationOfferVersion).where(
                ReservationOfferVersion.brand_id == row.brand_id,
                ReservationOfferVersion.active.is_(True),
                ReservationOfferVersion.offer_version_id != row.offer_version_id,
            )
        ).all()
        for old in current:
            old.active = False
    before = row.active
    row.active = data.active
    audit(db, actor=actor, action="reservation_offer_activation_changed", entity_type="reservation_offer", entity_id=row.offer_version_id, before={"active": before}, after=data.model_dump())
    db.commit()
    db.refresh(row)
    return row


def _offer_is_usable(offer: ReservationOfferVersion) -> bool:
    now = utcnow()
    return bool(
        offer.active
        and offer.legal_approved
        and offer.finance_approved
        and offer.pricing_approved
        and _aware(offer.valid_from) <= now <= _aware(offer.valid_to)
        and offer.price_snapshot_id
        and offer.terms_version_id
        and offer.technical_scope_version_id
    )


def create_reservation(db: Session, data: ReservationCreateIn, *, actor: str) -> ReservationRecord:
    if not data.terms_accepted:
        raise ValueError("Az aktív TermsVersion elfogadása nélkül fizetés nem indítható.")
    offer = db.scalar(select(ReservationOfferVersion).where(ReservationOfferVersion.offer_version_id == data.offer_version_id).with_for_update())
    if not offer or not _offer_is_usable(offer):
        raise ValueError("Az ajánlat nem aktív, lejárt vagy hiányzik valamelyik kötelező jóváhagyási kapuja.")
    duplicate = db.scalar(select(ReservationRecord).where(ReservationRecord.customer_email == data.customer_email, ReservationRecord.house_config_id == data.house_config_id, ReservationRecord.status.in_(RESERVATION_ACTIVE)))
    if duplicate:
        raise ValueError(f"Ehhez az ügyfélhez és konfigurációhoz már van aktív lekötési folyamat: {duplicate.reservation_id}.")
    project_id = _ensure_journey_project(db, data.project_id, customer_name=data.customer_name, responsible=None)
    row = ReservationRecord(
        reservation_id=_new_id("RSV"),
        project_id=project_id,
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
        offer_version_id=offer.offer_version_id,
        brand_id=offer.brand_id,
        house_plan_id=data.house_plan_id,
        house_config_id=data.house_config_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email,
        billing_name=data.billing_name,
        billing_address=data.billing_address,
        tax_number=data.tax_number,
        amount_huf=offer.reservation_amount_huf,
        price_snapshot_id=offer.price_snapshot_id,
        terms_version_id=offer.terms_version_id,
        technical_scope_version_id=offer.technical_scope_version_id,
        terms_accepted_at=utcnow(),
        next_action="Biztonságos fizetési szolgáltatói tranzakció indítása és callback ellenőrzése.",
        attribution_json=json.dumps(data.attribution, ensure_ascii=False),
    )
    db.add(row)
    db.flush()
    _ensure_customer_portal_access(
        db,
        project_id=project_id,
        customer_email=data.customer_email,
        contact_name=data.customer_name,
        source_type="reservation",
        source_id=row.reservation_id,
        actor=actor,
    )
    audit(db, actor=actor, action="reservation_payment_started", entity_type="reservation", entity_id=row.reservation_id, after={"offer_version_id": offer.offer_version_id, "price_snapshot_id": offer.price_snapshot_id, "terms_version_id": offer.terms_version_id, "amount_huf": str(row.amount_huf)})
    _emit(db, project_id=project_id, source_module="reservation-engine", event_type="PAYMENT_STARTED", object_type="Reservation", object_id=row.reservation_id, status=row.status, summary="A lekötési feltételeket elfogadták; a fizetés szolgáltatói visszaigazolásra vár.", actor=actor, financial_impact_huf=Decimal(str(row.amount_huf)), route_to=["crm", "financial-control"], payload={"offer_version_id": offer.offer_version_id, "price_snapshot_id": row.price_snapshot_id, "terms_version_id": row.terms_version_id, "house_plan_id": row.house_plan_id, "house_config_id": row.house_config_id})
    db.refresh(row)
    return row


def create_intent_declaration(
    db: Session,
    data: IntentDeclarationCreateIn,
    *,
    actor: str,
) -> IntentDeclarationRecord:
    if not data.terms_accepted or not data.consent:
        raise ValueError("A szándéknyilatkozathoz az aktív feltételek és az adatkezelési hozzájárulás elfogadása kötelező.")
    offer = db.scalar(
        select(ReservationOfferVersion).where(
            ReservationOfferVersion.offer_version_id == data.offer_version_id
        ).with_for_update()
    )
    if not offer or not _offer_is_usable(offer) or not offer.intent_declaration_enabled:
        raise ValueError("Ehhez az OfferVersionhöz nincs aktív, jóváhagyott szándéknyilatkozati út.")
    duplicate = db.scalar(
        select(IntentDeclarationRecord).where(
            IntentDeclarationRecord.customer_email == data.customer_email.strip().lower(),
            IntentDeclarationRecord.house_config_id == data.house_config_id,
            IntentDeclarationRecord.status.in_(INTENT_ACTIVE),
        )
    )
    if duplicate:
        raise ValueError(f"Ehhez az ügyfélhez és konfigurációhoz már tartozik aktív szándéknyilatkozat: {duplicate.intent_declaration_id}.")
    project_id = _ensure_journey_project(
        db,
        data.project_id,
        customer_name=data.customer_name,
        responsible="Értékesítés",
    )
    row = IntentDeclarationRecord(
        intent_declaration_id=_new_id("INT"),
        project_id=project_id,
        lead_id=data.lead_id,
        opportunity_id=data.opportunity_id,
        offer_version_id=offer.offer_version_id,
        brand_id=offer.brand_id,
        house_plan_id=data.house_plan_id,
        house_config_id=data.house_config_id,
        customer_name=data.customer_name,
        customer_email=data.customer_email.strip().lower(),
        customer_phone=data.customer_phone,
        target_start_window=data.target_start_window,
        project_scope=data.project_scope,
        plot_status=data.plot_status,
        price_snapshot_id=offer.price_snapshot_id,
        terms_version_id=offer.terms_version_id,
        technical_scope_version_id=offer.technical_scope_version_id,
        consent_version_id=data.consent_version_id,
        accepted_at=utcnow(),
        expires_at=utcnow() + timedelta(days=offer.intent_valid_days),
        cancellation_token=secrets.token_urlsafe(32),
        next_action="Értékesítői tartalmi ellenőrzés és kézbesítési bizonyíték rögzítése.",
        attribution_json=json.dumps(data.attribution, ensure_ascii=False),
    )
    db.add(row)
    db.flush()
    _ensure_customer_portal_access(
        db,
        project_id=project_id,
        customer_email=row.customer_email,
        contact_name=row.customer_name,
        source_type="intent_declaration",
        source_id=row.intent_declaration_id,
        actor=actor,
    )
    db.add(
        TaskRecord(
            task_id=f"TASK-INT-{row.intent_declaration_id[-8:]}-REVIEW",
            project_id=project_id,
            title="Prefab szándéknyilatkozat ellenőrzése",
            description=f"IntentDeclarationID: {row.intent_declaration_id}; OfferVersionID: {offer.offer_version_id}",
            assignee="Értékesítés",
            due_at=utcnow() + timedelta(days=1),
            priority="high",
            status="open",
            executive_relevance=False,
        )
    )
    audit(
        db,
        actor=actor,
        action="intent_declaration_submitted",
        entity_type="intent_declaration",
        entity_id=row.intent_declaration_id,
        after={
            "offer_version_id": row.offer_version_id,
            "price_snapshot_id": row.price_snapshot_id,
            "terms_version_id": row.terms_version_id,
            "technical_scope_version_id": row.technical_scope_version_id,
            "expires_at": row.expires_at.isoformat(),
        },
    )
    _emit(
        db,
        project_id=project_id,
        source_module="intent-declaration",
        event_type="INTENT_DECLARATION_SUBMITTED",
        object_type="IntentDeclaration",
        object_id=row.intent_declaration_id,
        status=row.status,
        summary="A fizetés nélküli Prefab szándéknyilatkozat verzióhelyesen beérkezett és emberi ellenőrzésre vár.",
        actor=actor,
        responsible="Értékesítés",
        route_to=["crm", "sales", "contract-generator", "my-imperial", "buildconfig"],
        payload={
            "lead_id": row.lead_id,
            "opportunity_id": row.opportunity_id,
            "offer_version_id": row.offer_version_id,
            "price_snapshot_id": row.price_snapshot_id,
            "terms_version_id": row.terms_version_id,
            "technical_scope_version_id": row.technical_scope_version_id,
            "house_plan_id": row.house_plan_id,
            "house_config_id": row.house_config_id,
            "payment_required": False,
        },
        next_action=row.next_action,
    )
    db.refresh(row)
    return row


def update_intent_declaration(
    db: Session,
    intent_declaration_id: str,
    data: IntentDeclarationUpdateIn,
    *,
    actor: str,
) -> IntentDeclarationRecord:
    row = db.scalar(
        select(IntentDeclarationRecord).where(
            IntentDeclarationRecord.intent_declaration_id == intent_declaration_id
        ).with_for_update()
    )
    if not row:
        raise KeyError(intent_declaration_id)
    if row.status != "changes_requested":
        raise ValueError("Csak módosításra visszaadott szándéknyilatkozat küldhető be újra.")
    if not data.consent:
        raise ValueError("Az újbóli beküldéshez adatkezelési hozzájárulás szükséges.")
    offer = db.scalar(select(ReservationOfferVersion).where(ReservationOfferVersion.offer_version_id == row.offer_version_id))
    if not offer or not _offer_is_usable(offer) or not offer.intent_declaration_enabled:
        raise ValueError("Az eredeti OfferVersion már nem aktív; új szándéknyilatkozat szükséges.")
    for field in ("house_plan_id", "house_config_id", "customer_phone", "target_start_window", "project_scope", "plot_status"):
        setattr(row, field, getattr(data, field))
    row.status = "submitted"
    row.review_note = None
    row.reviewed_by = None
    row.reviewed_at = None
    row.next_action = "Értékesítői újraellenőrzés és kézbesítési bizonyíték rögzítése."
    row.version += 1
    audit(db, actor=actor, action="intent_declaration_resubmitted", entity_type="intent_declaration", entity_id=row.intent_declaration_id, after=data.model_dump())
    _emit(db, project_id=row.project_id, source_module="intent-declaration", event_type="INTENT_DECLARATION_RESUBMITTED", object_type="IntentDeclaration", object_id=row.intent_declaration_id, status=row.status, summary="Az ügyfél a kért módosítások után újra beküldte a szándéknyilatkozatot.", actor=actor, responsible="Értékesítés", route_to=["crm", "sales", "my-imperial"], next_action=row.next_action)
    db.refresh(row)
    return row


def review_intent_declaration(
    db: Session,
    intent_declaration_id: str,
    data: IntentDeclarationReviewIn,
    *,
    actor: str,
) -> IntentDeclarationRecord:
    row = db.scalar(select(IntentDeclarationRecord).where(IntentDeclarationRecord.intent_declaration_id == intent_declaration_id).with_for_update())
    if not row:
        raise KeyError(intent_declaration_id)
    if row.status != "submitted":
        raise ValueError("Csak beküldött szándéknyilatkozat bírálható el.")
    if _aware(row.expires_at) <= utcnow():
        row.status = "expired"
        db.commit()
        raise ValueError("A szándéknyilatkozat érvényessége lejárt.")
    if data.action == "approve" and not data.delivery_evidence_url:
        raise ValueError("Jóváhagyáshoz kézbesítési vagy aláírási bizonyíték URL kötelező.")
    if data.action == "approve":
        offer = db.scalar(select(ReservationOfferVersion).where(ReservationOfferVersion.offer_version_id == row.offer_version_id))
        if not offer or not _offer_is_usable(offer) or not offer.intent_declaration_enabled:
            raise ValueError("A jóváhagyáshoz az eredeti OfferVersionnek továbbra is aktívnak és teljesen jóváhagyottnak kell lennie.")
        if (row.price_snapshot_id, row.terms_version_id, row.technical_scope_version_id) != (offer.price_snapshot_id, offer.terms_version_id, offer.technical_scope_version_id):
            raise ValueError("Az ajánlat-, ár-, feltétel- vagy műszaki verzió eltér; a jóváhagyás lezárt.")
    row.status = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}[data.action]
    row.reviewed_by = actor
    row.reviewed_at = utcnow()
    row.review_note = data.note
    row.delivery_evidence_url = data.delivery_evidence_url
    row.version += 1
    if data.action == "approve":
        row.next_action = "Szerződés-előkészítési csomag létrehozása és felelős értékesítői egyeztetés."
        db.add(TaskRecord(task_id=f"TASK-INT-{row.intent_declaration_id[-8:]}-CONTRACT", project_id=row.project_id, title="Prefab szerződés-előkészítési csomag", description=f"IntentDeclarationID: {row.intent_declaration_id}; TermsVersionID: {row.terms_version_id}", assignee="Értékesítés / jog", due_at=utcnow() + timedelta(days=5), priority="high", status="open", executive_relevance=True))
    elif data.action == "request_changes":
        row.next_action = "Az ügyfél módosítja és újra beküldi a szándéknyilatkozatot."
        db.add(TaskRecord(task_id=f"TASK-INT-{row.intent_declaration_id[-8:]}-CUSTOMER", project_id=row.project_id, title="Szándéknyilatkozat kért módosítása", description=data.note, assignee=row.customer_email, due_at=utcnow() + timedelta(days=5), priority="normal", status="open", executive_relevance=False))
    else:
        row.next_action = "Az elvesztési ok CRM-rögzítése és az ügyfél tájékoztatása."
    audit(db, actor=actor, action=f"intent_declaration_{data.action}", entity_type="intent_declaration", entity_id=row.intent_declaration_id, after=data.model_dump(mode="json"))
    _emit(db, project_id=row.project_id, source_module="intent-declaration", event_type=f"INTENT_DECLARATION_{row.status.upper()}", object_type="IntentDeclaration", object_id=row.intent_declaration_id, status=row.status, summary=f"A szándéknyilatkozat elbírálása: {row.status}. {data.note}", actor=actor, responsible="Értékesítés / jog" if data.action == "approve" else row.customer_email if data.action == "request_changes" else "Értékesítés", route_to=["crm", "sales", "contract-generator", "my-imperial"], payload={"delivery_evidence_url": row.delivery_evidence_url, "review_note": row.review_note}, severity="high" if data.action == "reject" else "info", next_action=row.next_action)
    db.refresh(row)
    return row


def withdraw_intent_declaration(db: Session, intent_declaration_id: str, *, actor: str, reason: str) -> IntentDeclarationRecord:
    row = db.scalar(select(IntentDeclarationRecord).where(IntentDeclarationRecord.intent_declaration_id == intent_declaration_id).with_for_update())
    if not row:
        raise KeyError(intent_declaration_id)
    if row.status not in INTENT_ACTIVE:
        raise ValueError("A szándéknyilatkozat ebből az állapotból nem vonható vissza.")
    row.status = "withdrawn"
    row.next_action = "Az ügyfél visszavonásának CRM-rögzítése."
    row.version += 1
    audit(db, actor=actor, action="intent_declaration_withdrawn", entity_type="intent_declaration", entity_id=row.intent_declaration_id, after={"reason": reason})
    _emit(db, project_id=row.project_id, source_module="intent-declaration", event_type="INTENT_DECLARATION_WITHDRAWN", object_type="IntentDeclaration", object_id=row.intent_declaration_id, status=row.status, summary=f"Az ügyfél visszavonta a szándéknyilatkozatot: {reason}", actor=actor, route_to=["crm", "sales", "contract-generator", "my-imperial"], next_action=row.next_action)
    db.refresh(row)
    return row


def convert_intent_declaration(db: Session, intent_declaration_id: str, contract_id: str, *, actor: str) -> IntentDeclarationRecord:
    row = db.scalar(select(IntentDeclarationRecord).where(IntentDeclarationRecord.intent_declaration_id == intent_declaration_id).with_for_update())
    if not row:
        raise KeyError(intent_declaration_id)
    if row.status != "approved":
        raise ValueError("Csak jóváhagyott szándéknyilatkozat adható át aláírt szerződésbe.")
    contract = db.scalar(select(ProjectObjectState).where(ProjectObjectState.project_id == row.project_id, ProjectObjectState.source_module == "contract_generator", ProjectObjectState.object_type == "Contract", ProjectObjectState.object_id == contract_id, ProjectObjectState.status == "signed"))
    if not contract:
        raise ValueError("A Contract Generatorban nincs ugyanilyen ProjectID-hoz igazolt, aláírt ContractID.")
    row.status = "converted"
    row.contract_id = contract_id
    row.next_action = "MyImperial projektaktiválás és projektmenedzseri átadás."
    row.version += 1
    audit(db, actor=actor, action="intent_declaration_converted", entity_type="intent_declaration", entity_id=row.intent_declaration_id, after={"contract_id": contract_id})
    _emit(db, project_id=row.project_id, source_module="intent-declaration", event_type="INTENT_DECLARATION_CONVERTED", object_type="IntentDeclaration", object_id=row.intent_declaration_id, status=row.status, summary="A jóváhagyott szándéknyilatkozat igazolt, aláírt szerződésbe került.", actor=actor, route_to=["crm", "contract-generator", "my-imperial", "project-control"], payload={"contract_id": contract_id}, next_action=row.next_action)
    db.refresh(row)
    return row


def expire_intent_declarations(db: Session, *, actor: str = "system") -> int:
    rows = db.scalars(select(IntentDeclarationRecord).where(IntentDeclarationRecord.status.in_(INTENT_ACTIVE), IntentDeclarationRecord.expires_at < utcnow())).all()
    for row in rows:
        row.status = "expired"
        row.next_action = "Új, aktuális OfferVersion szerinti szándéknyilatkozat szükséges."
        row.version += 1
        _emit(db, project_id=row.project_id, source_module="intent-declaration", event_type="INTENT_DECLARATION_EXPIRED", object_type="IntentDeclaration", object_id=row.intent_declaration_id, status=row.status, summary="A szándéknyilatkozat érvényessége lejárt.", actor=actor, route_to=["crm", "sales", "my-imperial"], next_action=row.next_action)
    return len(rows)


def record_payment_result(db: Session, reservation_id: str, data: ReservationPaymentResultIn, *, actor: str) -> tuple[ReservationRecord, ReservationPaymentRecord]:
    existing = db.scalar(select(ReservationPaymentRecord).where(ReservationPaymentRecord.idempotency_key == data.idempotency_key))
    if existing:
        reservation = db.scalar(select(ReservationRecord).where(ReservationRecord.reservation_id == existing.reservation_id))
        if existing.reservation_id != reservation_id:
            raise ValueError("Az idempotency-kulcs más ReservationID-hoz tartozik.")
        if reservation is None:
            raise KeyError(existing.reservation_id)
        return reservation, existing
    provider_replay = db.scalar(
        select(ReservationPaymentRecord).where(
            ReservationPaymentRecord.provider_reference == data.provider_reference
        )
    )
    if provider_replay:
        raise ValueError("A szolgáltatói tranzakcióhivatkozást már feldolgoztuk más idempotency-kulccsal.")
    row = db.scalar(select(ReservationRecord).where(ReservationRecord.reservation_id == reservation_id).with_for_update())
    if not row:
        raise KeyError(reservation_id)
    if row.status != "payment_pending":
        raise ValueError("A lekötés nem vár fizetési eredményre.")
    amount = Decimal(str(data.amount_huf))
    if data.status == "succeeded" and amount != Decimal(str(row.amount_huf)):
        raise ValueError("A sikeres tranzakció összege nem egyezik az aktív OfferVersion összegével.")
    if data.status == "succeeded" and not data.evidence_url:
        raise ValueError("Sikeres fizetéshez szolgáltatói bizonyíték URL kötelező.")
    payment = ReservationPaymentRecord(
        payment_id=_new_id("PAY"),
        reservation_id=row.reservation_id,
        provider=data.provider,
        provider_reference=data.provider_reference,
        idempotency_key=data.idempotency_key,
        amount_huf=amount,
        status=data.status,
        evidence_url=data.evidence_url,
        raw_result_json=json.dumps(data.raw_result, ensure_ascii=False),
    )
    db.add(payment)
    row.payment_id = payment.payment_id
    row.version += 1
    if data.status == "succeeded":
        offer = db.scalar(select(ReservationOfferVersion).where(ReservationOfferVersion.offer_version_id == row.offer_version_id))
        if not offer or not _offer_is_usable(offer):
            raise ValueError("A fizetési callback idején az OfferVersion már nem aktiválható.")
        row.status = "price_lock_active"
        row.price_lock_status = "active"
        row.price_lock_expires_at = utcnow() + timedelta(days=30 * offer.price_lock_months)
        row.next_action = "Telek-, finanszírozási és szerződés-előkészítési ügyfélút végrehajtása."
        event_type = "RESERVATION_ACTIVATED"
        routes = ["crm", "sales", "financial-control", "finance-intelligence", "contract-generator", "my-imperial", "plotcheck", "buildconfig"]
        summary = "A fizetés egyező és igazolt; a lekötés és az árgarancia aktív."
    else:
        row.status = "payment_failed"
        row.price_lock_status = "inactive"
        row.next_action = "Sikertelen fizetés okának kezelése vagy új tranzakció indítása új lekötési folyamatban."
        event_type = "PAYMENT_FAILED"
        routes = ["crm", "financial-control"]
        summary = "A fizetés sikertelen; aktív lekötés és árgarancia nem jött létre."
    audit(db, actor=actor, action="reservation_payment_result_recorded", entity_type="reservation", entity_id=row.reservation_id, after={**data.model_dump(mode="json"), "payment_id": payment.payment_id, "price_lock_status": row.price_lock_status})
    _emit(db, project_id=row.project_id, source_module="reservation-engine", event_type=event_type, object_type="Reservation", object_id=row.reservation_id, status=row.status, summary=summary, actor=actor, financial_impact_huf=amount, route_to=routes, payload={"payment_id": payment.payment_id, "provider_reference": payment.provider_reference, "offer_version_id": row.offer_version_id, "price_snapshot_id": row.price_snapshot_id, "terms_version_id": row.terms_version_id, "price_lock_expires_at": row.price_lock_expires_at.isoformat() if row.price_lock_expires_at else None}, severity="high" if data.status == "failed" else "info", next_action=row.next_action)
    if data.status == "succeeded":
        for key, title, assignee, days in (
            ("plot", "Telekút és PlotCheck indítása", "Műszaki előkészítés", 3),
            ("finance", "Finanszírozási előminősítés", "Pénzügy", 3),
            ("contract", "Lekötésből szerződés-előkészítés", "Értékesítés / jog", 7),
        ):
            db.add(TaskRecord(task_id=f"TASK-RSV-{row.reservation_id[-8:]}-{key.upper()}", project_id=row.project_id, title=title, description=f"ReservationID: {row.reservation_id}; OfferVersionID: {row.offer_version_id}", assignee=assignee, due_at=utcnow() + timedelta(days=days), priority="high", status="open", executive_relevance=key == "contract"))
        db.commit()
    db.refresh(row)
    db.refresh(payment)
    return row, payment


def transition_reservation(db: Session, reservation_id: str, data: ReservationLifecycleIn, *, actor: str) -> ReservationRecord:
    row = db.scalar(select(ReservationRecord).where(ReservationRecord.reservation_id == reservation_id).with_for_update())
    if not row:
        raise KeyError(reservation_id)
    allowed = {
        "cancel": {"payment_pending", "payment_failed", "price_lock_active"},
        "expire": {"price_lock_active"},
        "refund": {"price_lock_active", "converted"},
    }
    if row.status not in allowed[data.action]:
        raise ValueError("A kért életciklus-művelet ebből az állapotból nem engedélyezett.")
    if data.action == "refund" and not data.evidence_url:
        raise ValueError("Visszatérítéshez pénzügyi bizonyíték kötelező.")
    row.status = {"cancel": "cancelled", "expire": "expired", "refund": "refunded"}[data.action]
    row.price_lock_status = "inactive"
    row.version += 1
    row.next_action = "Az ügyfél, CRM, pénzügy és szerződéses projekciók egyeztetése."
    audit(db, actor=actor, action=f"reservation_{data.action}", entity_type="reservation", entity_id=row.reservation_id, after=data.model_dump(mode="json"))
    _emit(db, project_id=row.project_id, source_module="reservation-engine", event_type=f"RESERVATION_{row.status.upper()}", object_type="Reservation", object_id=row.reservation_id, status=row.status, summary=f"A lekötés állapota: {row.status}. Indok: {data.reason}", actor=actor, financial_impact_huf=Decimal(str(row.amount_huf)), route_to=["crm", "financial-control", "contract-generator", "my-imperial"], payload={"reason": data.reason, "evidence_url": data.evidence_url}, severity="high" if data.action == "refund" else "info", next_action=row.next_action)
    db.refresh(row)
    return row


def convert_reservation(db: Session, reservation_id: str, contract_id: str, *, actor: str) -> ReservationRecord:
    row = db.scalar(select(ReservationRecord).where(ReservationRecord.reservation_id == reservation_id).with_for_update())
    if not row:
        raise KeyError(reservation_id)
    if row.status != "price_lock_active":
        raise ValueError("Csak aktív árgaranciás lekötés konvertálható szerződéssé.")
    contract = db.scalar(select(ProjectObjectState).where(ProjectObjectState.project_id == row.project_id, ProjectObjectState.source_module == "contract_generator", ProjectObjectState.object_type == "Contract", ProjectObjectState.object_id == contract_id, ProjectObjectState.status == "signed"))
    if not contract:
        raise ValueError("A Contract Generatorban nincs ugyanilyen ProjectID-hoz igazolt, aláírt ContractID.")
    row.status = "converted"
    row.contract_id = contract_id
    row.next_action = "MyImperial projektaktiválás és projektmenedzseri átadás."
    row.version += 1
    audit(db, actor=actor, action="reservation_converted", entity_type="reservation", entity_id=row.reservation_id, after={"contract_id": contract_id})
    _emit(db, project_id=row.project_id, source_module="reservation-engine", event_type="RESERVATION_CONVERTED", object_type="Reservation", object_id=row.reservation_id, status=row.status, summary="Az aktív lekötés igazolt, aláírt szerződésbe konvertálva.", actor=actor, financial_impact_huf=Decimal(str(row.amount_huf)), route_to=["crm", "contract-generator", "my-imperial", "project-control", "financial-control"], payload={"contract_id": contract_id, "price_snapshot_id": row.price_snapshot_id, "terms_version_id": row.terms_version_id}, next_action=row.next_action)
    db.refresh(row)
    return row


def commercial_sales_workspace(db: Session) -> dict[str, Any]:
    _release_expired_holds(db)
    expire_intent_declarations(db)
    experiences = db.scalars(select(BookingExperienceVersion).order_by(BookingExperienceVersion.brand_id, desc(BookingExperienceVersion.created_at))).all()
    slots = db.scalars(select(BookingSlot).order_by(BookingSlot.starts_at).limit(100)).all()
    bookings = db.scalars(select(BookingRecord).order_by(desc(BookingRecord.created_at)).limit(100)).all()
    offers = db.scalars(select(ReservationOfferVersion).order_by(ReservationOfferVersion.brand_id, desc(ReservationOfferVersion.created_at))).all()
    reservations = db.scalars(select(ReservationRecord).order_by(desc(ReservationRecord.created_at)).limit(100)).all()
    intents = db.scalars(select(IntentDeclarationRecord).order_by(desc(IntentDeclarationRecord.created_at)).limit(100)).all()
    return {
        "experiences": experiences,
        "slots": slots,
        "bookings": bookings,
        "offers": offers,
        "reservations": reservations,
        "intents": intents,
        "metrics": {
            "available_slots": sum(1 for row in slots if row.status == "available"),
            "calendar_locked": sum(1 for row in bookings if row.status == "calendar_locked"),
            "confirmed_bookings": sum(1 for row in bookings if row.status == "confirmed"),
            "active_price_locks": sum(1 for row in reservations if row.price_lock_status == "active"),
            "payment_failures": sum(1 for row in reservations if row.status == "payment_failed"),
            "active_intents": sum(1 for row in intents if row.status in INTENT_ACTIVE),
            "approved_intents": sum(1 for row in intents if row.status == "approved"),
        },
    }


def my_imperial_workspace(db: Session, user: object) -> dict[str, Any]:
    expire_intent_declarations(db)
    role = str(getattr(user, "role", ""))
    email = str(getattr(user, "email", "")).strip().lower()
    internal = role in {"owner", "managing-director", "platform-admin", "sales", "project-manager", "finance", "legal", "designer"}
    access_stmt = select(CustomerPortalAccess).where(CustomerPortalAccess.active.is_(True))
    if not internal:
        access_stmt = access_stmt.where(CustomerPortalAccess.customer_email == email)
    accesses = db.scalars(access_stmt.order_by(desc(CustomerPortalAccess.updated_at))).all()
    project_ids = sorted({row.project_id for row in accesses})
    if not project_ids:
        return {"internal": internal, "accesses": [], "projects": [], "reservations": [], "intents": [], "customer_tasks": [], "object_states": [], "metrics": {"projects": 0, "active_reservations": 0, "active_intents": 0, "customer_actions": 0}}
    projects = db.scalars(select(ProjectRegistry).where(ProjectRegistry.project_id.in_(project_ids)).order_by(desc(ProjectRegistry.updated_at))).all()
    reservations = db.scalars(select(ReservationRecord).where(ReservationRecord.project_id.in_(project_ids)).order_by(desc(ReservationRecord.created_at))).all()
    intents = db.scalars(select(IntentDeclarationRecord).where(IntentDeclarationRecord.project_id.in_(project_ids)).order_by(desc(IntentDeclarationRecord.created_at))).all()
    task_stmt = select(TaskRecord).where(TaskRecord.project_id.in_(project_ids), TaskRecord.status.in_(["open", "in_progress", "waiting_customer"]))
    if not internal:
        task_stmt = task_stmt.where(TaskRecord.assignee == email)
    customer_tasks = db.scalars(task_stmt.order_by(TaskRecord.due_at)).all()
    visible_sources = ["plancheck", "change-control", "imperial-care", "reservation-engine", "intent-declaration"]
    object_states = db.scalars(select(ProjectObjectState).where(ProjectObjectState.project_id.in_(project_ids), ProjectObjectState.source_module.in_(visible_sources)).order_by(desc(ProjectObjectState.updated_at))).all()
    return {
        "internal": internal,
        "accesses": accesses,
        "projects": projects,
        "reservations": reservations,
        "intents": intents,
        "customer_tasks": customer_tasks,
        "object_states": object_states,
        "metrics": {
            "projects": len(project_ids),
            "active_reservations": sum(1 for row in reservations if row.status in RESERVATION_ACTIVE),
            "active_intents": sum(1 for row in intents if row.status in INTENT_ACTIVE),
            "customer_actions": len(customer_tasks),
        },
    }


def serialize_booking(row: BookingRecord) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name != "id"}


def serialize_reservation(row: ReservationRecord) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name != "id"}


def serialize_intent_declaration(row: IntentDeclarationRecord) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name != "id" and column.name != "cancellation_token"}
