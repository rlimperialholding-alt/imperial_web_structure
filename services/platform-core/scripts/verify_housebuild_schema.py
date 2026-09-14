"""Fail-closed HouseBuild persistence, hash-chain and UAT verification."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    HouseBuildCase,
    HouseBuildGate,
    HouseBuildValidation,
    HouseBuildVariant,
    WorkspaceDocument,
)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def main() -> int:
    errors: list[str] = []
    with SessionLocal() as db:
        cases = list(db.scalars(select(HouseBuildCase)))
        variants = list(db.scalars(select(HouseBuildVariant)))
        validations = list(db.scalars(select(HouseBuildValidation)))
        gates = list(db.scalars(select(HouseBuildGate)))
        documents = {
            row.document_id: row
            for row in db.scalars(
                select(WorkspaceDocument).where(
                    WorkspaceDocument.category == "housebuild_release_report"
                )
            )
        }
        by_case = {row.case_id: [] for row in cases}
        for row in variants:
            by_case.setdefault(row.case_id, []).append(row)
            payload = {
                "variant_id": row.variant_id,
                "variant_no": row.variant_no,
                "label": row.label,
                "strategy": row.strategy,
                "gross_area_m2": str(row.gross_area_m2),
                "net_area_m2": str(row.net_area_m2),
                "footprint_m2": str(row.footprint_m2),
                "width_m": str(row.width_m),
                "depth_m": str(row.depth_m),
                "floors": row.floors,
                "bedrooms": row.bedrooms,
                "bathrooms": row.bathrooms,
                "garage_spaces": row.garage_spaces,
                "roof_style": row.roof_style,
                "facade_style": row.facade_style,
                "orientation": row.orientation,
                "accessibility": row.accessibility,
                "estimated_catalog_price_huf": str(row.estimated_catalog_price_huf),
                "rooms": json.loads(row.rooms_json),
                "adjacency": json.loads(row.adjacency_json),
                "geometry": json.loads(row.geometry_json),
                "geometry_signature": row.geometry_signature,
            }
            if hashlib.sha256(canonical(payload).encode()).hexdigest() != row.content_sha256:
                errors.append(f"{row.variant_id}: content_sha256 mismatch")
        for row in cases:
            if len(by_case.get(row.case_id, [])) != 3:
                errors.append(f"{row.case_id}: expected 3 variants")
            if len([g for g in gates if g.case_id == row.case_id]) != 8:
                errors.append(f"{row.case_id}: expected 8 gates")
            if row.status == "released":
                selected = next(
                    (
                        item
                        for item in by_case[row.case_id]
                        if item.variant_id == row.selected_variant_id
                    ),
                    None,
                )
                if selected is None or selected.status != "released":
                    errors.append(f"{row.case_id}: released variant missing")
                if any(g.decision != "approved" for g in gates if g.case_id == row.case_id):
                    errors.append(f"{row.case_id}: non-approved release gate")
                document = documents.get(row.final_report_document_id)
                if document is None:
                    errors.append(f"{row.case_id}: release report missing")
                else:
                    metadata = json.loads(document.metadata_json or "{}")
                    path = Path(str(metadata.get("local_path") or ""))
                    if not path.is_file() or hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest() != metadata.get("sha256"):
                        errors.append(f"{row.case_id}: release report checksum failed")
        print(
            json.dumps(
                {
                    "cases": len(cases),
                    "variants": len(variants),
                    "validations": len(validations),
                    "gates": len(gates),
                    "reports": len(documents),
                    "errors": errors,
                },
                ensure_ascii=False,
            )
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
