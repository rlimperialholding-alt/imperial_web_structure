"""Kompakt UI-handler sweep a korábban fedetlen main.py POST/GET kezelőkre.

A suite a korábban 0–30%-ban fedett, üzletileg valós kezelőket söpri végig
determinisztikusan, szintetikus, hálózatmentes adatokkal: műszaki ügyek UI
életciklusa, felhasználó-adminisztráció, website-content-control release
műveletek, marketing-hozzájárulás és B2B CRM receipt — minden esetben a
sikeres ág mellett a jogosultsági/validációs fail-closed ágakkal.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    ContentAssetRecord,
    WorkspaceDocument,
    CopyBriefRecord,
    CreativeProductionRunRecord,
    MarketingLead,
    PartnerFieldAccess,
    PublicationBundleRecord,
    User,
    WebsiteRelease,
    WebsiteReleaseTarget,
)
from app.schemas import (
    B2BCRMReceiptIn,
    B2BTechnicalReviewIn,
    WebsiteSiteIn,
)
from app.services.b2b_project_intake import (
    capture_intake,
    leadership_decision,
    qualify_intake,
    queue_crm_handoff,
    record_financial_review,
    record_technical_review,
)
from app.seed import DEMO_PASSWORD
from app.services.technical_products import create_case, decide_case, get_case, review_gate, submit_case
from app.services.website_content import register_site


def _login(client, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": DEMO_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _user_id(db, email: str) -> int:
    row = db.scalar(select(User).where(User.email == email))
    assert row is not None
    return row.id


class TestTechnicalCaseUiSweep:
    def _case(self, db, suffix: str, actor: str = "designer@imperial.local") -> str:
        row = create_case(
            db,
            module_key="plancheck",
            project_id=f"PRJ-SWEEP-{suffix}",
            title=f"UI sweep műszaki ügy {suffix}",
            data={"document_refs": [f"DOC-{suffix}/v1"]},
            actor=actor,
        )
        submit_case(db, row["case_id"], actor)
        return row["case_id"]

    def test_create_gate_review_decision_ui_and_api(self, client, db) -> None:
        _login(client, "designer@imperial.local")
        created = client.post(
            "/technical/cases",
            data={
                "module_key": "plancheck",
                "project_id": "PRJ-SWEEP-UI",
                "title": "UI létrehozás sweep",
                "input": "{}",
                "document_refs": "DOC-UI/v1",
            },
            follow_redirects=False,
        )
        assert created.status_code in {302, 303}

        case_id = self._case(db, "GATE")
        gates = get_case(db, case_id)["gates"]
        gate_key = gates[0]["gate_key"]
        _login(client, "technical-prep@imperial.local")
        gate = client.post(
            f"/technical/cases/{case_id}/gates/{gate_key}",
            data={
                "status": "pass",
                "evidence": "Szintetikus UI kapu-bizonyíték.",
            },
            follow_redirects=False,
        )
        assert gate.status_code in {302, 303}

        remaining = [g["gate_key"] for g in gates if g["gate_key"] != gate_key]
        for remaining_key in remaining:
            review_gate(
                db,
                case_id,
                remaining_key,
                "pass",
                "Szintetikus UI maradék kapu.",
                "technical-prep@imperial.local",
            )
        _login(client, "managing-director@imperial.local")
        decision = client.post(
            f"/technical/cases/{case_id}/decision",
            data={
                "decision": "approved",
                "reason": "Szintetikus UI döntés.",
            },
            follow_redirects=False,
        )
        assert decision.status_code in {302, 303}

        api_case = self._case(db, "API", actor="technical-prep@imperial.local")
        for api_gate in get_case(db, api_case)["gates"]:
            review_gate(
                db,
                api_case,
                api_gate["gate_key"],
                "pass",
                "Szintetikus API előkészítő kapu.",
                "designer@imperial.local",
            )
        _login(client, "managing-director@imperial.local")
        api_decision = client.post(
            f"/api/technical/cases/{api_case}/decision",
            json={"decision": "approved", "reason": "Szintetikus API döntés."},
        )
        assert api_decision.status_code == 200

    def test_ui_negative_branches_fail_closed(self, client, db) -> None:
        _login(client, "customer@imperial.local")
        denied = client.post(
            "/technical/cases",
            data={
                "module_key": "plancheck",
                "project_id": "PRJ-SWEEP-NEG",
                "title": "Jogosulatlan ügy",
                "input": "{}",
            },
            follow_redirects=False,
        )
        assert denied.status_code == 403

        _login(client, "designer@imperial.local")
        canonical = client.post(
            "/technical/cases",
            data={
                "module_key": "plotcheck",
                "project_id": "PRJ-SWEEP-NEG",
                "title": "Kanonikus munkatérből tiltott",
                "input": "{}",
            },
            follow_redirects=False,
        )
        assert canonical.status_code == 409

        case_id = self._case(db, "NEG", actor="designer@imperial.local")
        bad_decision = client.post(
            f"/technical/cases/{case_id}/decision",
            data={"decision": "approved", "reason": "Négy szem megsértése"},
            follow_redirects=False,
        )
        assert bad_decision.status_code == 409
        missing = client.post(
            "/technical/cases/TECH-NEM-LETEZIK/decision",
            data={"decision": "approved", "reason": "Hiányzó ügy"},
            follow_redirects=False,
        )
        assert missing.status_code == 404


class TestAdminUserUpdateSweep:
    def test_role_update_and_negative_branches(self, client, db) -> None:
        _login(client, "owner@imperial.local")
        designer_id = _user_id(db, "designer@imperial.local")

        updated = client.post(
            f"/admin/users/{designer_id}",
            data={"role": "technical-prep", "active": "on"},
            follow_redirects=False,
        )
        assert updated.status_code in {302, 303}
        db.expire_all()
        assert _user_id(db, "designer@imperial.local") == designer_id
        row = db.scalar(select(User).where(User.id == designer_id))
        assert row is not None and row.role == "technical-prep"

        unknown_role = client.post(
            f"/admin/users/{designer_id}",
            data={"role": "NOT-A-ROLE", "active": "on"},
            follow_redirects=False,
        )
        assert unknown_role.status_code == 400

        missing = client.post(
            "/admin/users/999999",
            data={"role": "designer", "active": "on"},
            follow_redirects=False,
        )
        assert missing.status_code == 404

        self_disable = client.post(
            f"/admin/users/{_user_id(db, 'owner@imperial.local')}",
            data={"role": "owner"},
            follow_redirects=False,
        )
        assert self_disable.status_code == 409

        owner_row = db.scalar(select(User).where(User.email == "owner@imperial.local"))
        _login(client, "platform-admin@imperial.local")
        owner_guard = client.post(
            f"/admin/users/{owner_row.id}",
            data={"role": "designer", "active": "on"},
            follow_redirects=False,
        )
        assert owner_guard.status_code == 403

        _login(client, "designer@imperial.local")
        non_admin = client.post(
            f"/admin/users/{designer_id}",
            data={"role": "sales", "active": "on"},
            follow_redirects=False,
        )
        assert non_admin.status_code == 403


class TestWebsiteContentUiSweep:
    def _site_and_asset(self, db, suffix: str) -> tuple[str, str]:
        site = register_site(
            db,
            WebsiteSiteIn(
                brand_id="imperial",
                name=f"UI sweep webhely {suffix}",
                base_url="https://93.184.216.34/site-" + suffix.lower(),
                adapter_endpoint="https://93.184.216.34/internal/content-adapter",
                credential_ref=f"vault://website/sweep-{suffix.lower()}",
            ),
            "platform-admin@imperial.local",
            "platform-admin",
        )
        now = datetime.now(UTC)
        asset_id = f"ASSET-SWEEP-{suffix}"
        db.add(
            CopyBriefRecord(
                copy_brief_id=f"CB-SWEEP-{suffix}",
                brand_id="imperial",
                asset_type="knowledge_page",
                channel="web",
                status="STRATEGY_APPROVED",
                valid_from=now - timedelta(days=1),
                valid_until=now + timedelta(days=90),
                brief_json="{}",
                source_snapshot_hash="a" * 64,
                created_by="marketing@imperial.local",
            )
        )
        db.add(
            CreativeProductionRunRecord(
                generation_run_id=f"RUN-SWEEP-{suffix}",
                asset_id=asset_id,
                content_version=1,
                sequence_number=1,
                producer_identity="creative-producer",
                visual_direction_id=f"DIR-SWEEP-{suffix}",
                platform="web",
                width_px=1600,
                height_px=900,
                output_uri=f"s3://controlled-content/{suffix}.webp",
                output_sha256="b" * 64,
                generation_prompt_hash="c" * 64,
                contains_text=False,
                status="APPROVED",
                created_by="creative-producer",
            )
        )
        db.add(
            PublicationBundleRecord(
                bundle_id=f"BUNDLE-SWEEP-{suffix}",
                asset_id=asset_id,
                content_version=1,
                content_hash="e" * 64,
                visual_generation_run_id=f"RUN-SWEEP-{suffix}",
                assembly_run_id=f"ASM-SWEEP-{suffix}",
                assembler_identity="production-designer",
                bundle_hash="f" * 64,
                exports_json='{"web":"approved"}',
                pairing_rationale="Szintetikus UI sweep párosítás.",
                status="APPROVED",
                created_by="production-designer",
            )
        )
        db.add(
            ContentAssetRecord(
                asset_id=asset_id,
                copy_brief_id=f"CB-SWEEP-{suffix}",
                brand_id="imperial",
                asset_type="knowledge_page",
                channel="web",
                state="PUBLISHED",
                content_version=1,
                content_hash="e" * 64,
                content_json=json.dumps({"title": "UI sweep webtartalom", "body": "Jóváhagyott."}, ensure_ascii=False),
                gate_1_approved=True,
                expert_language_approved=True,
                expert_marketing_approved=True,
                copywriter_approved=True,
                four_gate_approved=True,
                editorial_approved=True,
                owner_approved=True,
                source_prevalidated=True,
                creative_director_approved=True,
                assembly_approved=True,
                campaign_package_approved=True,
                campaign_package_hash="e" * 64,
                campaign_artifact_set_hash="f" * 64,
                release_approved=True,
                live_review_approved=True,
                active_bundle_id=f"BUNDLE-SWEEP-{suffix}",
                publication_proof_id=f"PROOF-SWEEP-{suffix}",
                published_at=now,
                created_by="marketing@imperial.local",
            )
        )
        db.commit()
        return site.site_id, asset_id

    def test_release_smoke_receipt_rollback_ui(self, client, db) -> None:
        site_id, asset_id = self._site_and_asset(db, "A")
        _login(client, "marketing@imperial.local")

        release = client.post(
            "/website-content-control/releases",
            data={
                "asset_id": asset_id,
                "site_ids": site_id,
                "route_path": "/ui-sweep",
            },
            follow_redirects=False,
        )
        assert release.status_code in {302, 303}
        target = db.scalar(
            select(WebsiteReleaseTarget).where(WebsiteReleaseTarget.site_id == site_id)
        )
        assert target is not None
        release_row = db.scalar(
            select(WebsiteRelease).where(WebsiteRelease.asset_id == asset_id)
        )
        assert release_row is not None
        dispatch = client.post(
            f"/website-content-control/releases/{release_row.release_id}/dispatch",
            follow_redirects=False,
        )
        assert dispatch.status_code in {302, 303}

        receipt = client.post(
            f"/website-content-control/targets/{target.target_id}/receipt",
            data={
                "external_version_id": "v1-sweep",
                "published_url": target.canonical_url,
                "rendered_content_sha256": "e" * 64,
            },
            follow_redirects=False,
        )
        assert receipt.status_code in {302, 303}

        smoke = client.post(
            f"/website-content-control/targets/{target.target_id}/smoke",
            data={
                "http_status": "200",
                "rendered_content_sha256": "e" * 64,
                "link_pass": "on",
                "form_pass": "on",
                "schema_pass": "on",
                "canonical_pass": "on",
                "accessibility_pass": "on",
                "analytics_pass": "on",
                "crm_pass": "on",
                "privacy_pass": "on",
                "mobile_render_pass": "on",
            },
            follow_redirects=False,
        )
        assert smoke.status_code in {302, 303}

        rollback = client.post(
            "/website-content-control/releases/nonexistent-release/rollback",
            data={"reason": "Szintetikus hiányzó release."},
            follow_redirects=False,
        )
        assert rollback.status_code == 404

        _login(client, "subcontractor@imperial.local")
        denied = client.post(
            "/website-content-control/releases",
            data={
                "asset_id": asset_id,
                "site_ids": site_id,
                "route_path": "/tiltott",
            },
            follow_redirects=False,
        )
        assert denied.status_code in {302, 303, 403}


class TestMarketingConsentUiSweep:
    def test_consent_grant_withdraw_and_negatives(self, client, db) -> None:
        lead = MarketingLead(
            lead_id="MKL-SWEEP-01",
            dedupe_key=hashlib.sha256(b"ui-sweep-lead").hexdigest(),
            source="internal_record",
            channel="web",
            full_name="UI Sweep Érdeklődő",
            email="lead.sweep@imperial.example",
            privacy_notice_version="pn-2026-1",
            consent_management_token="cmt-ui-sweep-01",
            status="new",
            score=0,
        )
        db.add(lead)
        db.commit()

        _login(client, "marketing@imperial.local")
        granted = client.post(
            f"/marketing/automation/leads/{lead.lead_id}/consent",
            data={"decision": "grant", "source": "internal_record", "evidence": "Szintetikus UI hozzájárulási bizonyíték."},
            follow_redirects=False,
        )
        assert granted.status_code in {302, 303}
        withdrawn = client.post(
            f"/marketing/automation/leads/{lead.lead_id}/consent",
            data={"decision": "withdraw", "evidence": "Szintetikus UI visszavonási bizonyíték."},
            follow_redirects=False,
        )
        assert withdrawn.status_code in {302, 303}

        invalid = client.post(
            f"/marketing/automation/leads/{lead.lead_id}/consent",
            data={"decision": "telemarketing", "evidence": "Szintetikus UI érvénytelen döntés."},
            follow_redirects=False,
        )
        assert invalid.status_code == 400
        missing = client.post(
            "/marketing/automation/leads/MKL-NEM-LETEZIK/consent",
            data={"decision": "grant", "evidence": "Szintetikus UI hozzájárulási bizonyíték."},
            follow_redirects=False,
        )
        assert missing.status_code == 404


class TestB2BReceiptUiSweep:
    def test_receipt_ui_and_negative_branches(self, client, db) -> None:
        from app.schemas import B2BProjectIntakeIn

        document = WorkspaceDocument(
            document_id="DOC-B2B-UI-SWEEP",
            title="UI sweep B2B projektbrief",
            category="project_brief",
            source_system="google_drive",
            source_url="gdrive://b2b/ui-sweep",
            approval_status="approved",
            verification_status="verified",
            confidentiality="internal",
            owner="sales@imperial.local",
        )
        db.add(document)
        db.commit()

        intake = capture_intake(
            db,
            B2BProjectIntakeIn(
                source_system="lead-intelligence",
                source_external_id="SIG-UI-SWEEP",
                source_reference="gdrive://b2b/ui-sweep",
                source_content_sha256="a" * 64,
                lawful_basis="contract_request",
                source_use_approved=True,
                organization_name="UI Sweep Projekt Kft.",
                tax_number="12345678-2-41",
                website_domain="ui-sweep.example",
                contact_name="Sweep Elek",
                contact_email="sweep@ui-sweep.example",
                contact_phone="+36 30 111 2222",
                project_type="industrial",
                country="HU",
                city="Budapest",
                site_address="1111 Budapest, Sweep utca 1.",
                gross_floor_area_m2="5200",
                planned_start="2027-01-15",
                requested_deadline="2028-06-30",
                estimated_budget_huf="1500000000",
                project_summary="Szintetikus UI sweep vállalati projektigény.",
                document_ids=["DOC-B2B-UI-SWEEP"],
            ),
            "marketing@imperial.local",
            "marketing",
        )
        record_technical_review(
            db,
            intake.intake_id,
            B2BTechnicalReviewIn(
                decision="approved",
                delivery_model="design_and_build",
                capacity_fit="fit",
                site_feasibility="needs_plotcheck",
                complexity="high",
                note="Szintetikus UI sweep műszaki review.",
            ),
            "pm-reviewer@imperial.local",
            "project-manager",
        )
        from app.schemas import B2BFinancialReviewIn, B2BQualificationDecisionIn

        record_financial_review(
            db,
            intake.intake_id,
            B2BFinancialReviewIn(
                decision="conditional",
                budget_credibility="credible",
                funding_status="planned",
                preliminary_margin_band="előzetes 12–18%, nem ajánlat",
                assumptions=["Finanszírozási igazolás ajánlat előtt szükséges."],
                note="Szintetikus UI sweep pénzügyi előszűrés.",
            ),
            "finance-reviewer@imperial.local",
            "finance",
        )
        qualify_intake(
            db,
            intake.intake_id,
            B2BQualificationDecisionIn(
                decision="qualified",
                route="b2b_offer",
                assigned_sales_email="sales@imperial.local",
                next_action="Szintetikus UI sweep minősítés.",
                note="A műszaki és pénzügyi előszűrés alapján minősített igény.",
            ),
            "sales@imperial.local",
            "sales",
        )
        leadership_decision(
            db,
            intake.intake_id,
            B2BQualificationDecisionIn(
                decision="approved",
                route="strategic_b2b",
                assigned_sales_email="sales@imperial.local",
                next_action="Szintetikus UI sweep vezetői jóváhagyás.",
                note="Vezetőileg jóváhagyott stratégiai B2B igény.",
            ),
            "managing-director@imperial.local",
            "managing-director",
        )
        delivery = queue_crm_handoff(db, intake.intake_id, "sales@imperial.local", "sales")

        _login(client, "platform-admin@imperial.local")
        receipt = client.post(
            f"/b2b-project-intake/deliveries/{delivery.delivery_id}/receipt",
            data={
                "idempotency_key": delivery.idempotency_key,
                "payload_sha256": delivery.payload_sha256,
                "accepted": "true",
                "external_crm_id": "CRM-SWEEP-01",
            },
            follow_redirects=False,
        )
        assert receipt.status_code in {302, 303}

        _login(client, "sales@imperial.local")
        denied = client.post(
            f"/b2b-project-intake/deliveries/{delivery.delivery_id}/receipt",
            data={
                "idempotency_key": delivery.idempotency_key,
                "payload_sha256": delivery.payload_sha256,
                "accepted": "true",
            },
            follow_redirects=False,
        )
        assert denied.status_code == 403
