from __future__ import annotations

import json

from sqlalchemy import text

from app.database import engine

CHECKS = {
    "missing_current_revision": """
        SELECT count(*) FROM plancheck_cases c
        LEFT JOIN plancheck_revisions r ON r.revision_id = c.current_revision_id
        WHERE r.id IS NULL OR r.case_id <> c.case_id OR r.version <> c.current_revision
    """,
    "current_not_latest": """
        SELECT count(*) FROM plancheck_cases c
        WHERE c.current_revision <> (
          SELECT max(r.version) FROM plancheck_revisions r WHERE r.case_id = c.case_id
        )
    """,
    "eligible_without_gates": """
        SELECT count(*) FROM plancheck_revisions r
        WHERE r.final_eligible = true AND (
          SELECT count(*) FROM plancheck_gates g
          WHERE g.revision_id = r.revision_id AND g.decision = 'approved'
        ) <> 5
    """,
    "eligible_with_high_open_assumption": """
        SELECT count(*) FROM plancheck_revisions r
        WHERE r.final_eligible = true AND EXISTS (
          SELECT 1 FROM plancheck_assumptions a
          WHERE a.revision_id = r.revision_id AND a.impact = 'high' AND a.status = 'open'
        )
    """,
    "eligible_with_low_confidence": """
        SELECT count(*) FROM plancheck_revisions
        WHERE final_eligible = true AND confidence_class NOT IN ('A','B')
    """,
    "finalized_without_report": """
        SELECT count(*) FROM plancheck_cases
        WHERE status IN ('sendable','not_sendable') AND (
          final_report_document_id IS NULL OR finalized_by IS NULL OR finalized_at IS NULL
        )
    """,
    "duplicate_gate_actors": """
        SELECT count(*) FROM (
          SELECT revision_id, decided_by, count(*) AS uses
          FROM plancheck_gates
          WHERE decided_by IS NOT NULL
          GROUP BY revision_id, decided_by
          HAVING count(*) > 1
        ) duplicate_actors
    """,
}


def main() -> None:
    with engine.connect() as connection:
        counts = {
            name: int(connection.execute(text(query)).scalar_one())
            for name, query in CHECKS.items()
        }
        rows = int(connection.execute(text("SELECT count(*) FROM plancheck_cases")).scalar_one())
    errors = [name for name, count in counts.items() if count]
    print(json.dumps({"ok": not errors, "errors": errors, "counts": {"cases": rows, **counts}}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
