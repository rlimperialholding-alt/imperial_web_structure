from __future__ import annotations

import json

from sqlalchemy import desc, func, select

from app.database import SessionLocal
from app.models import EnterpriseCanonicalRecord, ImportJob


def main() -> None:
    with SessionLocal() as db:
        total = db.scalar(select(func.count(EnterpriseCanonicalRecord.id))) or 0
        entity_rows = db.execute(
            select(
                EnterpriseCanonicalRecord.domain,
                EnterpriseCanonicalRecord.entity_type,
                func.count(EnterpriseCanonicalRecord.id),
            )
            .group_by(
                EnterpriseCanonicalRecord.domain,
                EnterpriseCanonicalRecord.entity_type,
            )
            .order_by(
                EnterpriseCanonicalRecord.domain,
                EnterpriseCanonicalRecord.entity_type,
            )
        ).all()
        latest_job = db.scalar(
            select(ImportJob)
            .where(ImportJob.source_key == "crm-migrated-data")
            .order_by(desc(ImportJob.completed_at), desc(ImportJob.id))
            .limit(1)
        )
        summary = json.loads(latest_job.summary_json or "{}") if latest_job else {}
        print(
            json.dumps(
                {
                    "canonical_total": total,
                    "entities": {
                        f"{domain}/{entity_type}": count
                        for domain, entity_type, count in entity_rows
                    },
                    "latest_import": {
                        "job_id": latest_job.job_id if latest_job else None,
                        "status": latest_job.status if latest_job else None,
                        "total": summary.get("inserted", 0)
                        + summary.get("updated", 0)
                        + summary.get("unchanged", 0),
                        "entities": summary.get("entities", {}),
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
