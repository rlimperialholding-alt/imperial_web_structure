from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

import app.services.house_designer_submission as submission_service
from app.config import settings
from app.models import (
    BookingExperienceVersion,
    BookingRecord,
    BookingSlot,
    CalendarEntry,
    HouseDesignEstimateSnapshot,
    HouseDesignRenderRevision,
    HouseDesignRevision,
    HouseDesignScheduleSnapshot,
    HouseDesignSession,
    HouseDesignSubmission,
    HouseDesignSubmissionDecision,
    RegulatoryComplianceRun,
)
from app.services.house_designer import (
    ActorScope,
    HouseDesignerError,
    apply_session_command,
    create_session,
)
from app.services.house_designer_geometry import canonical_sha256
from app.services.house_designer_submission import (
    HOUSE_DESIGN_NOTICE_VERSION,
    HOUSE_DESIGN_TERMS_VERSION,
    approval_panel,
    approve_current_design,
    book_consultation,
    list_submission_queue,
    submission_detail,
    submit_order_request,
    transition_submission_review,
)


def _seed_approvable_bundle(db, revision: HouseDesignRevision) -> tuple[str, str]:
    now = datetime.now(UTC)
    db.add(
        RegulatoryComplianceRun(
            run_id="RCR-SUBMISSION-PASS",
            session_id=revision.session_id,
            revision_id=revision.revision_id,
            ruleset_id="RULESET-PROVED",
            ruleset_sha256="1" * 64,
            input_sha256="2" * 64,
            outcome="PASS",
            blocker_count=0,
            error_count=0,
            warning_count=0,
            engine_version="test-v1",
            completed_at=now,
            created_by="customer-subject",
        )
    )
    db.add(
        HouseDesignEstimateSnapshot(
            estimate_id="HDE-SUBMISSION-SANDBOX",
            session_id=revision.session_id,
            design_revision_id=revision.revision_id,
            input_sha256="3" * 64,
            net_min_huf=Decimal("70000000"),
            net_max_huf=Decimal("80000000"),
            vat_rate=Decimal("0.27"),
            gross_min_huf=Decimal("88900000"),
            gross_max_huf=Decimal("101600000"),
            line_items_json="[]",
            assumptions_json="[]",
            exclusions_json="[]",
            provider="sandbox-test",
            non_production=True,
            valid_until=now + timedelta(days=14),
            canonical_sha256="4" * 64,
            created_by="customer-subject",
        )
    )
    db.add(
        HouseDesignScheduleSnapshot(
            schedule_id="HDT-SUBMISSION-SANDBOX",
            session_id=revision.session_id,
            design_revision_id=revision.revision_id,
            input_sha256="3" * 64,
            duration_min_workdays=120,
            duration_max_workdays=160,
            phases_json="[]",
            assumptions_json="[]",
            provider="sandbox-test",
            non_production=True,
            valid_until=now + timedelta(days=7),
            canonical_sha256="5" * 64,
            created_by="customer-subject",
        )
    )
    render_id = "HDV-SUBMISSION-SANDBOX"
    db.add(
        HouseDesignRenderRevision(
            render_id=render_id,
            session_id=revision.session_id,
            design_revision_id=revision.revision_id,
            revision_no=1,
            geometry_lock_sha256=canonical_sha256(__import__("json").loads(revision.geometry_json)),
            prompt="Világos vakolat és fa burkolat",
            provider="sandbox-test",
            provider_job_id="submission-test-render",
            qa_json='{"geometryLockVerified":true}',
            status="ready",
            non_production=True,
            created_by="customer-subject",
        )
    )
    experience_id = "BOOKING-HD-CONSULT-V1"
    db.add(
        BookingExperienceVersion(
            experience_id=experience_id,
            brand_id="imperial",
            version="1",
            display_name="Háztervező személyes konzultáció",
            cta_label="Időpontfoglalás",
            trust_copy="A tervet az Imperial értékesítőjével tekintjük át.",
            confirmation_copy="Az időpontot a naptári visszaigazolás véglegesíti.",
            theme_key="imperial",
            active=True,
            policy_json="{}",
            created_by="sales@imperial.local",
        )
    )
    slot_id = "SLOT-HD-CONSULT-1"
    db.add(
        BookingSlot(
            slot_id=slot_id,
            experience_id=experience_id,
            brand_id="imperial",
            booking_type="online",
            calendar_resource_id="sales-consultation-1",
            advisor_email="sales@imperial.local",
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=3, hours=1),
            capacity=1,
            status="available",
            created_by="sales@imperial.local",
        )
    )
    db.commit()
    return render_id, slot_id


def test_customer_approval_consultation_and_sandbox_order_gate(db):
    actor = ActorScope("customer-subject", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=actor,
        brand_id="imperial",
        title="Konzultációs mintaház",
        command_id=str(uuid4()),
    )
    revision = db.scalar(
        select(HouseDesignRevision).where(
            HouseDesignRevision.revision_id == design["revision"]["revisionId"]
        )
    )
    render_id, slot_id = _seed_approvable_bundle(db, revision)

    snapshot = approve_current_design(
        db,
        session_id=design["sessionId"],
        actor=actor,
        selected_render_id=render_id,
        terms_version_id=HOUSE_DESIGN_TERMS_VERSION,
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        terms_accepted=True,
        notice_accepted=True,
    )
    replay = approve_current_design(
        db,
        session_id=design["sessionId"],
        actor=actor,
        selected_render_id=render_id,
        terms_version_id=HOUSE_DESIGN_TERMS_VERSION,
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        terms_accepted=True,
        notice_accepted=True,
    )
    assert replay["snapshotId"] == snapshot["snapshotId"]
    assert snapshot["productionReady"] is False

    panel = approval_panel(db, session_id=design["sessionId"], actor=actor)
    assert panel["currentSnapshot"]["snapshotId"] == snapshot["snapshotId"]
    assert [row["slotId"] for row in panel["consultationSlots"]] == [slot_id]
    assert panel["orderGate"]["open"] is False
    assert any("produkciós" in reason for reason in panel["orderGate"]["reasons"])

    command_id = str(uuid4())
    consultation = book_consultation(
        db,
        session_id=design["sessionId"],
        actor=actor,
        snapshot_id=snapshot["snapshotId"],
        slot_id=slot_id,
        customer_name="Teszt Ügyfél",
        customer_email="customer@example.com",
        customer_phone="+36301234567",
        plot_status="saját telek",
        planned_start="6–12 hónap",
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        notice_accepted=True,
        idempotency_key=command_id,
    )
    consultation_replay = book_consultation(
        db,
        session_id=design["sessionId"],
        actor=actor,
        snapshot_id=snapshot["snapshotId"],
        slot_id=slot_id,
        customer_name="Teszt Ügyfél",
        customer_email="customer@example.com",
        customer_phone="+36301234567",
        plot_status="saját telek",
        planned_start="6–12 hónap",
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        notice_accepted=True,
        idempotency_key=command_id,
    )
    assert consultation_replay["submissionId"] == consultation["submissionId"]
    assert consultation["bookingStatus"] == "calendar_locked"
    assert consultation["calendarSyncStatus"] == "pending"
    assert db.scalar(select(func.count(BookingRecord.id))) == 1
    assert db.scalar(select(func.count(HouseDesignSubmission.id))) == 1
    assert db.scalar(select(func.count(CalendarEntry.id))) == 1

    with pytest.raises(HouseDesignerError) as blocked:
        submit_order_request(
            db,
            session_id=design["sessionId"],
            actor=actor,
            snapshot_id=snapshot["snapshotId"],
            notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
            notice_accepted=True,
            idempotency_key=str(uuid4()),
        )
    assert blocked.value.code == "order_gate_closed"

    current = design["revision"]
    changed = apply_session_command(
        db,
        session_id=design["sessionId"],
        actor=actor,
        base_revision_id=current["revisionId"],
        base_canonical_sha256=current["canonicalSha256"],
        command_id=str(uuid4()),
        command_type="set_north",
        payload={"northAngleDeg": 15},
    )
    assert changed["status"] == "STALE"
    assert (
        approval_panel(db, session_id=design["sessionId"], actor=actor)["currentSnapshot"] is None
    )


def test_approval_rejects_non_owner_and_missing_compliance(db):
    owner = ActorScope("customer-owner", "imperial-holding", frozenset({"imperial"}))
    staff = ActorScope(
        "sales-staff", "imperial-holding", frozenset({"imperial"}), can_read_all_owned=True
    )
    design = create_session(
        db,
        actor=owner,
        brand_id="imperial",
        title="Tulajdonosi jóváhagyás",
        command_id=str(uuid4()),
    )
    assert approval_panel(db, session_id=design["sessionId"], actor=staff)["canAct"] is False
    with pytest.raises(HouseDesignerError) as forbidden:
        approve_current_design(
            db,
            session_id=design["sessionId"],
            actor=staff,
            selected_render_id="missing",
            terms_version_id=HOUSE_DESIGN_TERMS_VERSION,
            notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
            terms_accepted=True,
            notice_accepted=True,
        )
    assert forbidden.value.code == "session_not_found"
    with pytest.raises(HouseDesignerError) as missing:
        approve_current_design(
            db,
            session_id=design["sessionId"],
            actor=owner,
            selected_render_id="missing",
            terms_version_id=HOUSE_DESIGN_TERMS_VERSION,
            notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
            terms_accepted=True,
            notice_accepted=True,
        )
    assert missing.value.code == "compliance_pass_required"


def test_submission_detail_hides_other_customer_records(db):
    owner = ActorScope("customer-owner", "imperial-holding", frozenset({"imperial"}))
    outsider = ActorScope("customer-outsider", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=owner,
        brand_id="imperial",
        title="Beküldés olvasási hatókör",
        command_id=str(uuid4()),
    )
    submission = HouseDesignSubmission(
        submission_id="HDSUB-READ-SCOPE",
        tenant_id="imperial-holding",
        brand_id="imperial",
        session_id=design["sessionId"],
        snapshot_id="HDA-READ-SCOPE",
        snapshot_sha256="9" * 64,
        submission_type="ORDER_REQUEST",
        status="RECEIVED",
        customer_subject_id=owner.subject_id,
        idempotency_key=str(uuid4()),
        attribution_json="{}",
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        notice_accepted_at=datetime.now(UTC),
        created_by=owner.subject_id,
    )
    db.add(submission)
    db.commit()

    assert (
        submission_detail(db, submission_id=submission.submission_id, actor=owner)["submissionType"]
        == "ORDER_REQUEST"
    )
    with pytest.raises(HouseDesignerError) as hidden:
        submission_detail(db, submission_id=submission.submission_id, actor=outsider)
    assert hidden.value.code == "session_not_found"
    assert hidden.value.status_code == 404


def test_order_gate_honors_runtime_kill_switch(db, monkeypatch):
    actor = ActorScope("customer-kill-switch", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=actor,
        brand_id="imperial",
        title="Runtime order gate",
        command_id=str(uuid4()),
    )
    monkeypatch.setattr(
        submission_service,
        "settings",
        replace(settings, house_design_order_intake_enabled=False),
    )

    panel = approval_panel(db, session_id=design["sessionId"], actor=actor)

    assert any(
        "környezeti megrendelésfogadási kill switch" in reason
        for reason in panel["orderGate"]["reasons"]
    )


def _review_submission(db, *, project_id: str = "PROJECT-HD-REVIEW"):
    owner = ActorScope("customer-review-owner", "imperial-holding", frozenset({"imperial"}))
    design = create_session(
        db,
        actor=owner,
        brand_id="imperial",
        title="Review state machine",
        command_id=str(uuid4()),
    )
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == design["sessionId"])
    )
    session.project_id = project_id
    session.status = "SUBMITTED"
    submission = HouseDesignSubmission(
        submission_id=f"HDSUB-{uuid4().hex[:16]}",
        tenant_id="imperial-holding",
        brand_id="imperial",
        session_id=design["sessionId"],
        snapshot_id=f"HDA-{uuid4().hex[:16]}",
        snapshot_sha256="d" * 64,
        submission_type="ORDER_REQUEST",
        status="RECEIVED",
        customer_subject_id=owner.subject_id,
        project_id=project_id,
        idempotency_key=str(uuid4()),
        attribution_json="{}",
        notice_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        notice_accepted_at=datetime.now(UTC),
        created_by=owner.subject_id,
    )
    db.add(submission)
    db.commit()
    reviewer = ActorScope(
        "ITEP-REVIEWER",
        "imperial-holding",
        frozenset({"imperial"}),
        project_ids=frozenset({project_id}),
    )
    return owner, reviewer, submission


def test_submission_review_is_scoped_idempotent_and_gate_complete(db):
    _, reviewer, submission = _review_submission(db)
    outsider = ActorScope("ITEP-OUTSIDER", "imperial-holding", frozenset({"imperial"}))
    assert list_submission_queue(db, actor=outsider) == []
    assert [row["submissionId"] for row in list_submission_queue(db, actor=reviewer)] == [
        submission.submission_id
    ]

    first_key = str(uuid4())
    first = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="start_sales_review",
        note="Értékesítési teljességi ellenőrzés elindítva.",
        expected_row_version=1,
        idempotency_key=first_key,
    )
    assert first["status"] == "SALES_REVIEW" and first["rowVersion"] == 2
    replay = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="start_sales_review",
        note="Értékesítési teljességi ellenőrzés elindítva.",
        expected_row_version=1,
        idempotency_key=first_key,
    )
    assert replay["rowVersion"] == 2
    with pytest.raises(HouseDesignerError) as collision:
        transition_submission_review(
            db,
            submission_id=submission.submission_id,
            actor=reviewer,
            actor_role="sales",
            action="forward_design_review",
            note="Eltérő művelet ugyanazzal a kulccsal nem engedhető.",
            expected_row_version=2,
            idempotency_key=first_key,
        )
    assert collision.value.code == "idempotency_collision"

    detail = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="forward_design_review",
        note="Az értékesítési adatok teljesek, tervezői review indul.",
        expected_row_version=2,
        idempotency_key=str(uuid4()),
    )
    assert detail["status"] == "DESIGN_REVIEW"
    with pytest.raises(HouseDesignerError) as missing_gates:
        transition_submission_review(
            db,
            submission_id=submission.submission_id,
            actor=reviewer,
            actor_role="designer",
            action="accept",
            note="A terv műszakilag elfogadható és továbbítható.",
            expected_row_version=3,
            idempotency_key=str(uuid4()),
        )
    assert missing_gates.value.code == "submission_gate_reviews_required"

    compliance = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=replace(reviewer, subject_id="ITEP-LEGAL"),
        actor_role="legal",
        action="confirm_compliance",
        note="A snapshot compliance bizonyítéka és provenance kötése ellenőrizve.",
        expected_row_version=3,
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(HouseDesignerError) as same_reviewer:
        transition_submission_review(
            db,
            submission_id=submission.submission_id,
            actor=replace(reviewer, subject_id="ITEP-LEGAL"),
            actor_role="owner",
            action="confirm_pricing",
            note="Ugyanaz a személy nem hagyhatja jóvá mindkét ellenőrzési sávot.",
            expected_row_version=compliance["rowVersion"],
            idempotency_key=str(uuid4()),
        )
    assert same_reviewer.value.code == "submission_four_eyes_required"
    pricing = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=replace(reviewer, subject_id="ITEP-FINANCE"),
        actor_role="finance",
        action="confirm_pricing",
        note="Az ár- és kapacitás snapshot érvényessége ellenőrizve.",
        expected_row_version=compliance["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    accepted = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=replace(reviewer, subject_id="ITEP-DESIGNER"),
        actor_role="designer",
        action="accept",
        note="A tervezői review lezárult, a csomag belsőleg elfogadva.",
        expected_row_version=pricing["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    assert accepted["status"] == "ACCEPTED"
    assert [row["reviewLane"] for row in accepted["decisions"]] == [
        "sales",
        "sales",
        "compliance",
        "pricing",
        "design",
    ]
    assert db.scalar(select(func.count(HouseDesignSubmissionDecision.id))) == 5


def test_changes_requested_unlocks_new_revision_and_customer_cancel_is_owner_only(db):
    owner, reviewer, submission = _review_submission(db, project_id="PROJECT-HD-CHANGES")
    transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="start_sales_review",
        note="Az értékesítési review megkezdődött a dokumentált csomagon.",
        expected_row_version=1,
        idempotency_key=str(uuid4()),
    )
    changed = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="request_changes",
        note="A telekadat és a műszaki csomag pontosítása szükséges.",
        expected_row_version=2,
        idempotency_key=str(uuid4()),
    )
    assert changed["status"] == "CHANGES_REQUESTED"
    session = db.scalar(
        select(HouseDesignSession).where(HouseDesignSession.session_id == submission.session_id)
    )
    assert session.status == "STALE"
    with pytest.raises(HouseDesignerError) as forbidden:
        transition_submission_review(
            db,
            submission_id=submission.submission_id,
            actor=reviewer,
            actor_role="sales",
            action="cancel",
            note="Belső szereplő nem vonhatja vissza az ügyfél kérelmét.",
            expected_row_version=3,
            idempotency_key=str(uuid4()),
        )
    assert forbidden.value.code == "submission_cancel_forbidden"
    cancelled = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=owner,
        actor_role="customer",
        action="cancel",
        note="Az ügyfél a kérelmet saját döntése alapján visszavonja.",
        expected_row_version=3,
        idempotency_key=str(uuid4()),
    )
    assert cancelled["status"] == "CANCELLED"


def test_review_cycle_requires_fresh_confirmations_after_consultation_loop(db):
    _, reviewer, submission = _review_submission(db, project_id="PROJECT-HD-REVIEW-CYCLE")
    first = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="start_sales_review",
        note="Az első értékesítési ellenőrzési ciklus dokumentáltan elindult.",
        expected_row_version=1,
        idempotency_key=str(uuid4()),
    )
    design = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="forward_design_review",
        note="Az első tervezői ellenőrzési ciklus dokumentáltan elindult.",
        expected_row_version=first["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    compliance = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=replace(reviewer, subject_id="ITEP-CYCLE-LEGAL"),
        actor_role="legal",
        action="confirm_compliance",
        note="Az első ciklus compliance bizonyítékai ellenőrzésre kerültek.",
        expected_row_version=design["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    pricing = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=replace(reviewer, subject_id="ITEP-CYCLE-FINANCE"),
        actor_role="finance",
        action="confirm_pricing",
        note="Az első ciklus pricing bizonyítékai ellenőrzésre kerültek.",
        expected_row_version=compliance["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    now = datetime.now(UTC)
    experience = BookingExperienceVersion(
        experience_id="BOOKING-EXPERIENCE-HD-REVIEW-CYCLE",
        brand_id=submission.brand_id,
        version="review-cycle-v1",
        display_name="Synthetic review cycle",
        cta_label="Konzultáció",
        trust_copy="Kizárólag szintetikus tesztadat.",
        confirmation_copy="Kizárólag szintetikus tesztadat.",
        theme_key="imperial",
        active=True,
        policy_json="{}",
        created_by="test",
    )
    slot = BookingSlot(
        slot_id="SLOT-HD-REVIEW-CYCLE",
        experience_id=experience.experience_id,
        brand_id=submission.brand_id,
        booking_type="consultation",
        calendar_resource_id="synthetic-review-cycle",
        advisor_email="synthetic@example.invalid",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=1),
        capacity=1,
        status="available",
        created_by="test",
    )
    booking = BookingRecord(
        booking_id="BOOKING-HD-REVIEW-CYCLE",
        slot_id=slot.slot_id,
        project_id=submission.project_id,
        brand_id=submission.brand_id,
        booking_type="consultation",
        customer_email="synthetic@example.invalid",
        customer_name="Synthetic Review Cycle",
        customer_phone="+36000000000",
        project_description="Kizárólag szintetikus review-ciklus teszt.",
        plot_status="synthetic",
        planned_start="synthetic",
        consent_version_id=HOUSE_DESIGN_NOTICE_VERSION,
        consent_at=now,
        status="calendar_locked",
        cancellation_token=str(uuid4()),
    )
    db.add_all((experience, slot, booking))
    db.commit()
    consultation = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="link_consultation",
        note="További konzultáció szükséges az új review-ciklus előtt.",
        expected_row_version=pricing["rowVersion"],
        idempotency_key=str(uuid4()),
        booking_id=booking.booking_id,
    )
    sales_again = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="start_sales_review",
        note="A konzultáció után új értékesítési review-ciklus indult.",
        expected_row_version=consultation["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    design_again = transition_submission_review(
        db,
        submission_id=submission.submission_id,
        actor=reviewer,
        actor_role="sales",
        action="forward_design_review",
        note="A konzultáció után új tervezői review-ciklus indult.",
        expected_row_version=sales_again["rowVersion"],
        idempotency_key=str(uuid4()),
    )
    with pytest.raises(HouseDesignerError) as stale_confirmations:
        transition_submission_review(
            db,
            submission_id=submission.submission_id,
            actor=replace(reviewer, subject_id="ITEP-CYCLE-DESIGNER"),
            actor_role="designer",
            action="accept",
            note="Korábbi ciklus jóváhagyásaival nem lehet elfogadni a csomagot.",
            expected_row_version=design_again["rowVersion"],
            idempotency_key=str(uuid4()),
        )
    assert stale_confirmations.value.code == "submission_gate_reviews_required"


def test_submission_review_fails_closed_without_canonical_project(db):
    _, reviewer, submission = _review_submission(db, project_id="PROJECT-HD-MISSING-GATE")
    submission.project_id = None
    db.commit()

    with pytest.raises(HouseDesignerError) as missing_project:
        transition_submission_review(
            db,
            submission_id=submission.submission_id,
            actor=reviewer,
            actor_role="sales",
            action="start_sales_review",
            note="Projektazonosító nélkül a review nem indulhat el biztonságosan.",
            expected_row_version=1,
            idempotency_key=str(uuid4()),
        )

    assert missing_project.value.code == "submission_project_missing"
