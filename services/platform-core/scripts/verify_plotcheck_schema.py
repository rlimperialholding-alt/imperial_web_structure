"""Fail-closed integrity checks for the canonical PlotCheck database state."""

from __future__ import annotations

import json
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    PlotCheckAssessment,
    PlotCheckAction,
    PlotCheckCase,
    PlotCheckEvidence,
    PlotCheckGate,
    PlotRuleSet,
    WorkspaceDocument,
)
from app.services.plotcheck import GATE_EVIDENCE, GATE_KEYS


def main() -> int:
    errors: list[str] = []
    with SessionLocal() as db:
        rules = {row.rule_set_id: row for row in db.scalars(select(PlotRuleSet))}
        cases = list(db.scalars(select(PlotCheckCase)))
        evidence = list(db.scalars(select(PlotCheckEvidence)))
        gates = list(db.scalars(select(PlotCheckGate)))
        assessments = {row.assessment_id: row for row in db.scalars(select(PlotCheckAssessment))}
        actions = list(db.scalars(select(PlotCheckAction)))
        reports = {row.document_id: row for row in db.scalars(select(WorkspaceDocument).where(WorkspaceDocument.category == "plotcheck_report"))}
        evidence_by_case: dict[str, dict[str, PlotCheckEvidence]] = {}
        gates_by_case: dict[str, list[PlotCheckGate]] = {}
        for row in evidence:
            evidence_by_case.setdefault(row.case_id, {})[row.evidence_id] = row
            if len(row.source_sha256) != 64:
                errors.append(f"invalid evidence SHA-256: {row.evidence_id}")
            if row.verified and (not row.verified_by or not row.verified_at or row.verified_by.lower() == row.created_by.lower()):
                errors.append(f"invalid evidence four-eyes verification: {row.evidence_id}")
        for row in gates:
            gates_by_case.setdefault(row.case_id, []).append(row)
            if row.decision == "approved":
                ids = json.loads(row.evidence_ids_json or "[]")
                rows = evidence_by_case.get(row.case_id, {})
                supplied = {rows[item].category for item in ids if item in rows and rows[item].verified}
                missing = GATE_EVIDENCE.get(row.gate_key, set()) - supplied
                if missing:
                    errors.append(f"approved gate missing verified evidence: {row.case_id}:{row.gate_key}:{sorted(missing)}")
        for row in actions:
            if row.status == "completed" and (
                not row.completion_evidence_ref
                or not row.completion_evidence_sha256
                or len(row.completion_evidence_sha256) != 64
                or not row.completed_by
                or not row.completed_at
            ):
                errors.append(f"completed action missing evidence: {row.action_id}")
        for case in cases:
            rule = rules.get(case.rule_set_id)
            if rule is None:
                errors.append(f"missing rule snapshot: {case.case_id}")
                continue
            if rule.lifecycle_status == "uat" and not case.project_id.startswith("PRJ-UAT-"):
                errors.append(f"UAT rule used by non-UAT project: {case.case_id}")
            if rule.lifecycle_status not in {"verified", "retired", "uat"} or not rule.verified_at:
                errors.append(f"unverified rule used by case: {case.case_id}")
            final = case.status in {"fit", "fit_with_conditions", "redesign_required", "not_suitable"}
            if final:
                assessment = assessments.get(case.final_assessment_id or "")
                if assessment is None or assessment.preliminary:
                    errors.append(f"final case missing final assessment: {case.case_id}")
                if case.final_report_document_id not in reports:
                    errors.append(f"final case missing report record: {case.case_id}")
                case_gates = gates_by_case.get(case.case_id, [])
                if len(case_gates) != len(GATE_KEYS) or any(row.decision != "approved" for row in case_gates):
                    errors.append(f"final case missing approved gates: {case.case_id}")
                if case.finalized_by and case.finalized_by.lower() == case.created_by.lower():
                    errors.append(f"final case violates four-eyes: {case.case_id}")
    summary = {
        "rules": len(rules), "cases": len(cases), "evidence": len(evidence),
        "gates": len(gates), "actions": len(actions), "assessments": len(assessments), "reports": len(reports),
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
