"""Verify persistent BuildConfig invariants and release evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    BuildConfigCase,
    BuildConfigGate,
    BuildConfigValidation,
    BuildConfigVersion,
    WorkspaceDocument,
)

EXPECTED_VALIDATIONS = {
    "source_integrity": "source",
    "houseplan_binding": "houseplan",
    "option_compatibility": "compatibility",
    "bom_balance": "bom",
    "pricing_integrity": "pricing",
    "margin_policy": "margin",
    "cashflow_coverage": "cashflow",
    "capacity_commitment": "capacity",
}


def main() -> None:
    errors: list[str] = []
    with SessionLocal() as db:
        cases = list(db.scalars(select(BuildConfigCase)))
        versions = list(db.scalars(select(BuildConfigVersion)))
        for case in cases:
            current = db.scalar(
                select(BuildConfigVersion).where(
                    BuildConfigVersion.version_id == case.current_version_id,
                    BuildConfigVersion.case_id == case.case_id,
                )
            )
            if current is None:
                errors.append(f"{case.case_id}: current_version hiányzik")
                continue
            validations = list(
                db.scalars(
                    select(BuildConfigValidation).where(
                        BuildConfigValidation.version_id == current.version_id
                    )
                )
            )
            gates = list(
                db.scalars(
                    select(BuildConfigGate).where(BuildConfigGate.version_id == current.version_id)
                )
            )
            validation_by_key = {row.validation_key: row for row in validations}
            gate_by_key = {row.gate_key: row for row in gates}
            if len(validations) != 8 or set(validation_by_key) != set(EXPECTED_VALIDATIONS):
                errors.append(f"{current.version_id}: validációkészlet hibás")
            if len(gates) != 10:
                errors.append(f"{current.version_id}: nem tíz kapu található")
            for validation_key, gate_key in EXPECTED_VALIDATIONS.items():
                validation = validation_by_key.get(validation_key)
                gate = gate_by_key.get(gate_key)
                if validation is None or gate is None:
                    continue
                expected = "approved" if validation.decision == "pass" else "rejected"
                if gate.decision != expected or gate.evidence_sha256 != validation.evidence_sha256:
                    errors.append(f"{current.version_id}: {gate_key} kapu eltér a validációtól")
            bom = json.loads(current.bom_json)
            if (
                hashlib.sha256(
                    json.dumps(
                        bom,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                != current.bom_sha256
            ):
                errors.append(f"{current.version_id}: BOM hash hibás")
            if case.status == "approved":
                if current.status != "approved" or not case.final_report_document_id:
                    errors.append(f"{case.case_id}: jóváhagyott állapot hiányos")
                    continue
                document = db.scalar(
                    select(WorkspaceDocument).where(
                        WorkspaceDocument.document_id == case.final_report_document_id
                    )
                )
                if document is None:
                    errors.append(f"{case.case_id}: riportdokumentum hiányzik")
                    continue
                metadata = json.loads(document.metadata_json)
                path = Path(str(metadata.get("local_path") or ""))
                if not path.is_file() or hashlib.sha256(
                    path.read_bytes()
                ).hexdigest() != metadata.get("sha256"):
                    errors.append(f"{case.case_id}: riport SHA-256 hibás")
        result = {
            "cases": len(cases),
            "versions": len(versions),
            "validations": db.scalar(select(func.count()).select_from(BuildConfigValidation)),
            "gates": db.scalar(select(func.count()).select_from(BuildConfigGate)),
            "reports": db.scalar(
                select(func.count())
                .select_from(WorkspaceDocument)
                .where(WorkspaceDocument.source_system == "buildconfig")
            ),
            "errors": errors,
        }
        print(json.dumps(result, ensure_ascii=False))
        if errors:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
