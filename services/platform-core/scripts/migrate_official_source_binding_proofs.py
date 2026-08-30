from __future__ import annotations

import json

from sqlalchemy import select

from app.database import SessionLocal
from app.growth_ops import service
from app.growth_ops.models import GrowthSignal, OutreachMessage
from app.models import AuditLog

MIGRATION_ID = "official-architect-source-binding-proofs-20260829-v1"
REGISTRY_VERSION = "2026-08-29-architect-dynamic-v1"
REGISTRY_SHA256 = "be08f46c246cb4c67c70a1dfffd8d6c2d7c2c9a8d4f7aa6cd5490c1f87b10bd7"
AUTHORITY_REGISTRY_ID = "IMPERIAL_REAL_ESTATE_DISCOVERY_SOURCES_HU_V1"
AUTHORITY_REGISTRY_VERSION = 1
AUTHORITY_REGISTRY_SHA256 = (
    "38e3d2dda5dbed631e68cdf2a7c23208422fba50221bb961d318963a224d2b18"
)
TARGETS = (
    service.OfficialSourceBindingProofTarget(
        signal_id="SIG-71F32121D8334448B5CC",
        outreach_id="OUT-52129201A8FD471FAD82",
        source_id="DYNAMIC_HU_ARCHIKON_HU",
        binding_sha256=(
            "f52deece65604c903af6c8b66497e3b15df5d6c7c77187f767f3e5bab1d88610"
        ),
    ),
    service.OfficialSourceBindingProofTarget(
        signal_id="SIG-33B757A82D294AB4A61D",
        outreach_id="OUT-5924E9C9D25B474E93ED",
        source_id="DYNAMIC_HU_KOZTI_HU",
        binding_sha256=(
            "51abeb398a860e9f72ae2edeb6299e7bc2619d484ccc6b16b3c39e2a50c6fc56"
        ),
    ),
    service.OfficialSourceBindingProofTarget(
        signal_id="SIG-679455AC10764820A380",
        outreach_id="OUT-2179A02A9A0848E09582",
        source_id="DYNAMIC_HU_NAPUR_HU",
        binding_sha256=(
            "eb6944f448d691ded455654ae8f64cfbc2c09eb47f98bf09c6073619547f692e"
        ),
    ),
)


def _independent_readback(expected_proof_ids: list[int]) -> dict[str, object]:
    with SessionLocal() as db:
        proof_ids: list[int] = []
        queue_states: list[dict[str, object]] = []
        for target in TARGETS:
            row = db.scalar(
                select(OutreachMessage).where(
                    OutreachMessage.outreach_id == target.outreach_id
                )
            )
            signal = db.scalar(
                select(GrowthSignal).where(GrowthSignal.signal_id == target.signal_id)
            )
            if row is None or signal is None:
                raise RuntimeError("official_source_binding_migration_readback_missing")
            proof = service._official_source_binding_proof_audit(db, row, signal)
            if proof is None:
                raise RuntimeError(
                    "official_source_binding_migration_readback_proof_invalid"
                )
            proof_ids.append(proof.id)
            queue_states.append(
                {
                    "signal_id": signal.signal_id,
                    "outreach_id": row.outreach_id,
                    "source_id": signal.source_id,
                    "status": row.status,
                    "claimed_by": row.claimed_by,
                    "provider_message_id": row.provider_message_id,
                    "sent_at": row.sent_at,
                }
            )
        completions = db.scalars(
            select(AuditLog).where(
                AuditLog.action
                == "growth_official_source_binding_proof_migration_completed",
                AuditLog.entity_type == "growth_source_binding_migration",
                AuditLog.entity_id == MIGRATION_ID,
            )
        ).all()
        if len(completions) != 1:
            raise RuntimeError(
                "official_source_binding_migration_readback_completion_not_unique"
            )
        completion_payload = json.loads(completions[0].after_json or "{}")
        migration_hmac = str(completion_payload.pop("migration_hmac_sha256", ""))
        if (
            proof_ids != expected_proof_ids
            or completion_payload.get("email_sent") is not False
            or not migration_hmac
            or migration_hmac
            != service._official_source_receipt_hmac(completion_payload)
            or any(
                state["status"] != "queued"
                or state["claimed_by"] is not None
                or state["provider_message_id"] is not None
                or state["sent_at"] is not None
                for state in queue_states
            )
            or service.writes_unlocked()
        ):
            raise RuntimeError("official_source_binding_migration_readback_mismatch")
        return {
            "migration_audit_id": completions[0].id,
            "proof_audit_ids": proof_ids,
            "match_count": len(proof_ids),
            "queue_states": queue_states,
            "writes_unlocked": False,
            "email_sent": False,
        }


def main() -> None:
    with SessionLocal() as db:
        proof_ids = service.migrate_official_source_binding_proofs_locked(
            db,
            targets=TARGETS,
            migration_id=MIGRATION_ID,
            expected_registry_version=REGISTRY_VERSION,
            expected_registry_sha256=REGISTRY_SHA256,
            expected_authority_registry_id=AUTHORITY_REGISTRY_ID,
            expected_authority_registry_version=AUTHORITY_REGISTRY_VERSION,
            expected_authority_registry_sha256=AUTHORITY_REGISTRY_SHA256,
        )
    print(json.dumps(_independent_readback(proof_ids), sort_keys=True, default=str))


if __name__ == "__main__":
    main()
