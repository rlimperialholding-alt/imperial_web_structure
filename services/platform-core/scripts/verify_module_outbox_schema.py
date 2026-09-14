from __future__ import annotations

import hashlib
import json

from sqlalchemy import text

from app.database import engine

CHECKS = {
    "sent_without_delivery_evidence": """
        SELECT count(*) FROM cc_outbox o
        LEFT JOIN cc_module_inbox i ON i.message_id = o.message_id
        WHERE o.status = 'sent' AND (
          o.delivery_mode <> 'internal_inbox' OR o.delivery_mode IS NULL OR
          o.delivery_receipt_json IS NULL OR o.delivered_at IS NULL OR i.id IS NULL
        )
    """,
    "inbox_without_registered_module": """
        SELECT count(*) FROM cc_module_inbox i
        LEFT JOIN cc_modules m ON m.module_key = i.destination_module
        WHERE m.id IS NULL
    """,
    "inbox_hash_mismatch": """
        SELECT count(*) FROM cc_module_inbox i
        JOIN cc_outbox o ON o.message_id = i.message_id
        WHERE o.payload_sha256 IS NULL OR o.payload_sha256 <> i.payload_sha256
    """,
    "inbox_destination_mismatch": """
        SELECT count(*) FROM cc_module_inbox i
        JOIN cc_outbox o ON o.message_id = i.message_id
        WHERE i.requested_destination <> o.destination_module
    """,
    "pending_with_internal_receipt": """
        SELECT count(*) FROM cc_module_inbox i
        JOIN cc_outbox o ON o.message_id = i.message_id
        WHERE o.status IN ('pending','retry','dead_letter')
    """,
}


def main() -> None:
    with engine.connect() as connection:
        counts = {
            name: int(connection.execute(text(query)).scalar_one())
            for name, query in CHECKS.items()
        }
        rows = connection.execute(
            text(
                "SELECT i.delivery_id, i.payload_json, i.payload_sha256, "
                "o.delivery_receipt_json FROM cc_module_inbox i "
                "JOIN cc_outbox o ON o.message_id = i.message_id"
            )
        ).mappings()
        invalid_receipts = 0
        invalid_payload_hashes = 0
        total = 0
        for row in rows:
            total += 1
            canonical = json.dumps(
                json.loads(row["payload_json"]),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != row["payload_sha256"]:
                invalid_payload_hashes += 1
            try:
                receipt = json.loads(row["delivery_receipt_json"] or "")
            except json.JSONDecodeError:
                invalid_receipts += 1
                continue
            if receipt.get("delivery_id") != row["delivery_id"]:
                invalid_receipts += 1
    counts["invalid_payload_hashes"] = invalid_payload_hashes
    counts["invalid_receipts"] = invalid_receipts
    errors = [name for name, count in counts.items() if count]
    print(json.dumps({"ok": not errors, "errors": errors, "counts": {"inbox": total, **counts}}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
