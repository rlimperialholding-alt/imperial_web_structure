from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ModuleInboxDelivery, OutboxMessage
from app.schemas import EventIn
from app.services.integration import ingest_event, process_outbox


def main() -> None:
    token = uuid4().hex[:10].upper()
    event_id = f"EVT-UAT-OUTBOX-{token}"
    project_id = f"PRJ-UAT-OUTBOX-{token}"
    with SessionLocal() as db:
        event, created = ingest_event(
            db,
            EventIn(
                event_id=event_id,
                dedupe_key=f"uat:outbox:{token}",
                project_id=project_id,
                source_module="control-center",
                event_type="OUTBOX_DELIVERY_UAT",
                object_type="IntegrationUAT",
                object_id=f"OUTBOX-UAT-{token}",
                status="test_only",
                payload={
                    "project_name": f"Outbox UAT {token}",
                    "summary": "Tartós, belső modul-inbox kézbesítési próba.",
                    "test_only": True,
                    "executed_at": datetime.now(UTC).isoformat(),
                },
                route_to=["crm", "my-imperial", "buildconfig"],
            ),
            actor="platform-outbox-uat",
        )
        result = process_outbox(db)
        messages = list(
            db.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.source_event_id == event_id)
                .order_by(OutboxMessage.destination_module)
            )
        )
        receipts = list(
            db.scalars(
                select(ModuleInboxDelivery)
                .where(ModuleInboxDelivery.source_event_id == event_id)
                .order_by(ModuleInboxDelivery.destination_module)
            )
        )
        if not created or len(messages) != 3 or len(receipts) != 3:
            raise SystemExit("Az outbox UAT nem hozott létre három igazolt kézbesítést.")
        if any(message.status != "sent" for message in messages):
            raise SystemExit("Az outbox UAT legalább egy üzenete nem sent állapotú.")
        if {row.destination_module for row in receipts} != {
            "crm",
            "my-imperial",
            "buildconfig",
        }:
            raise SystemExit("Az outbox UAT célmoduljai eltérnek a várt készlettől.")
        print(
            json.dumps(
                {
                    "ok": True,
                    "event_id": event.event_id,
                    "project_id": project_id,
                    "test_only": True,
                    "process_result": result,
                    "deliveries": [
                        {
                            "delivery_id": row.delivery_id,
                            "destination_module": row.destination_module,
                            "payload_sha256": row.payload_sha256,
                            "status": row.status,
                        }
                        for row in receipts
                    ],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
