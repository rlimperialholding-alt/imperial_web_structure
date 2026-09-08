from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.growth_ops.models import (
    GrowthAccountStop,
    GrowthOutreachReconciliation,
    OutreachMessage,
)
from app.growth_ops.partnerpoint import _access_token, fetch_snapshot
from app.growth_ops.registry import GrowthRegistry

EXPECTED_CONTROL_SET_SIZE = 85
LEGACY_HANDOFF_STATUS = "CENTRAL_QUEUE_HANDOFF_BLOCKED_ADAPTER_UNAVAILABLE"
HISTORICAL_RESCOPED_RECORD_IDS = {"OUT-260825-002", "FU-260829-005"}
_EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+", re.I)


def _padded(row: list[str], size: int) -> list[str]:
    return row[:size] + [""] * max(0, size - len(row))


def _gmail_json(token: str, url: str) -> dict[str, Any]:
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}),
        timeout=45,
    ) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError("gmail_response_invalid")
    return payload


def _gmail_search(token: str, query: str, *, maximum: int = 20) -> list[str]:
    params = urllib.parse.urlencode({"q": query, "maxResults": maximum})
    payload = _gmail_json(
        token, f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{params}"
    )
    return [str(item["id"]) for item in payload.get("messages") or [] if item.get("id")]


def _gmail_raw(token: str, message_id: str) -> dict[str, Any]:
    payload = _gmail_json(
        token,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        f"{urllib.parse.quote(message_id)}?format=raw",
    )
    raw_value = str(payload.get("raw") or "")
    raw = base64.urlsafe_b64decode(raw_value + "=" * (-len(raw_value) % 4))
    message = BytesParser(policy=policy.default).parsebytes(raw)
    return {
        "gmail_message_id": message_id,
        "gmail_thread_id": str(payload.get("threadId") or ""),
        "internal_date_ms": int(payload.get("internalDate") or 0),
        "rfc_message_id": str(message.get("Message-ID") or ""),
        "from": str(message.get("From") or ""),
        "to": str(message.get("To") or ""),
        "subject": str(message.get("Subject") or ""),
        "mime_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _gmail_evidence(token: str, emails: list[str]) -> dict[str, Any]:
    domains = sorted({email.rsplit("@", 1)[-1] for email in emails if "@" in email})
    addresses = sorted(set(emails))
    targets = domains or addresses
    sent_ids: list[str] = []
    reply_ids: list[str] = []
    bounce_ids: list[str] = []
    for target in targets:
        sent_ids.extend(_gmail_search(token, f"in:sent newer_than:365d to:({target})"))
        reply_ids.extend(_gmail_search(token, f"newer_than:365d from:({target})"))
    for email in addresses:
        bounce_ids.extend(
            _gmail_search(
                token,
                f'newer_than:365d from:(mailer-daemon OR postmaster) "{email}"',
                maximum=10,
            )
        )
    sent = [_gmail_raw(token, value) for value in dict.fromkeys(sent_ids[:20])]
    replies = [_gmail_raw(token, value) for value in dict.fromkeys(reply_ids[:20])]
    bounces = [_gmail_raw(token, value) for value in dict.fromkeys(bounce_ids[:10])]
    earliest_sent_ms = min(
        (item["internal_date_ms"] for item in sent if item["internal_date_ms"]),
        default=0,
    )
    replies_after_sent = [
        item
        for item in replies
        if not earliest_sent_ms or item["internal_date_ms"] >= earliest_sent_ms
    ]
    return {
        "sent": sent,
        "replies_after_sent": replies_after_sent,
        "bounces": bounces,
    }


def _account_stops(db, emails: list[str]) -> list[GrowthAccountStop]:
    keys = []
    for email in emails:
        if "@" not in email:
            continue
        keys.extend((f"email:{email}", f"domain:{email.rsplit('@', 1)[-1]}"))
    if not keys:
        return []
    return db.scalars(
        select(GrowthAccountStop).where(
            GrowthAccountStop.active.is_(True), GrowthAccountStop.account_key.in_(keys)
        )
    ).all()


def _server_outreach(db, emails: list[str]) -> list[dict[str, Any]]:
    if not emails:
        return []
    rows = db.scalars(
        select(OutreachMessage)
        .where(func.lower(OutreachMessage.recipient_email).in_(emails))
        .order_by(OutreachMessage.created_at.desc())
    ).all()
    return [
        {
            "outreach_id": row.outreach_id,
            "status": row.status,
            "provider_message_id": row.provider_message_id,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            "last_error": row.last_error,
            "release_present": bool(row.release_token_hash),
            "signal_id": row.signal_id,
        }
        for row in rows
    ]


def _classification(
    *,
    pipeline: list[str],
    universe: list[str],
    stops: list[GrowthAccountStop],
    gmail: dict[str, Any],
    server: list[dict[str, Any]],
    duplicate: bool,
) -> tuple[str, str]:
    stop_kinds = {row.stop_kind for row in stops}
    combined = " ".join((*pipeline, *universe)).casefold()
    if stop_kinds.intersection({"response", "rejection"}) or gmail["replies_after_sent"]:
        return "REPLIED_STOP", "Reply or rejection evidence requires account-level stop"
    if stop_kinds.intersection({"dnc", "complaint", "hard_suppression"}) or any(
        marker in combined for marker in ("dnc", "do_not_contact", "opt_out", "complaint")
    ):
        return "DNC_STOP", "DNC, complaint or hard-suppression evidence is active"
    if "bounce" in stop_kinds or gmail["bounces"] or "bounce" in combined:
        return "BOUNCE_BLOCK", "Bounce evidence blocks the current recipient route"
    if "existing_relationship" in stop_kinds or any(
        marker in combined for marker in ("owner_manual_only", "meglévő aktív üzleti kapcsolat")
    ):
        return "OWNER_MANUAL_ONLY", "Existing relationship requires owner handling"
    if gmail["sent"]:
        return "ALREADY_SENT", "Gmail Sent MIME readback exists"
    if any(item["provider_message_id"] for item in server):
        return "SEND_UNVERIFIED_REVIEW", "Server claims provider acceptance without Gmail match"
    if duplicate:
        return "DUPLICATE_STOP", "Another handoff row resolves to the same recipient route"
    if (
        universe[3] == "MINŐSÍTVE – KÖZPONTI ÁTADÁSRA KÉSZ"
        and universe[21].startswith("PASS")
        and any(item["status"] in {"queued", "claimed"} for item in server)
    ):
        return "READY_TO_SEND", "Current live-revalidated production queue record exists"
    return "STALE_REQUALIFY", "Legacy package has no current send proof and must be requalified"


def _historical_control_rows(
    pipeline_rows: list[list[str]],
) -> list[tuple[int, list[str]]]:
    return [
        (number, row)
        for number, row in enumerate(pipeline_rows[1:], start=2)
        if row[5] == LEGACY_HANDOFF_STATUS or row[0] in HISTORICAL_RESCOPED_RECORD_IDS
    ]


def main() -> None:
    snapshot = fetch_snapshot()
    universe_rows = [_padded(row, 23) for row in snapshot["Partner_Universe"]]
    pipeline_rows = [_padded(row, 15) for row in snapshot["Outreach_Pipeline"]]
    universe_by_candidate = {row[0]: row for row in universe_rows[1:] if row[0]}
    control_rows = _historical_control_rows(pipeline_rows)
    if len(control_rows) != EXPECTED_CONTROL_SET_SIZE:
        raise RuntimeError(f"partnerpoint_control_set_size_changed:{len(control_rows)}")
    token = _access_token(
        GrowthRegistry.load(include_runtime_sources=False).brand_binding("imperial").secret
    )
    results: list[dict[str, Any]] = []
    seen_recipient_sets: set[tuple[str, ...]] = set()
    with SessionLocal() as db:
        for sheet_row, pipeline in control_rows:
            candidate_id = pipeline[1]
            universe = universe_by_candidate.get(candidate_id, [""] * 23)
            emails = sorted(
                set(_EMAIL_RE.findall(" ".join((universe[10], pipeline[13])).casefold()))
            )
            recipient_key = tuple(emails)
            duplicate = bool(recipient_key and recipient_key in seen_recipient_sets)
            if recipient_key:
                seen_recipient_sets.add(recipient_key)
            gmail = _gmail_evidence(token, emails)
            stops = _account_stops(db, emails)
            server = _server_outreach(db, emails)
            classification, reason = _classification(
                pipeline=pipeline,
                universe=universe,
                stops=stops,
                gmail=gmail,
                server=server,
                duplicate=duplicate,
            )
            evidence = {
                "sheet_row": sheet_row,
                "pipeline_status": pipeline[5],
                "template_id": pipeline[10],
                "candidate_status": universe[3],
                "candidate_hard_gate": universe[21],
                "gmail": gmail,
                "account_stops": [
                    {
                        "stop_id": item.stop_id,
                        "account_key": item.account_key,
                        "stop_kind": item.stop_kind,
                        "source_event_id": item.source_event_id,
                    }
                    for item in stops
                ],
                "server_outreach": server,
            }
            source_record_id = pipeline[0] or f"SHEETROW-{sheet_row}"
            row = db.scalar(
                select(GrowthOutreachReconciliation).where(
                    GrowthOutreachReconciliation.source_record_id == source_record_id
                )
            )
            if row is None:
                row = GrowthOutreachReconciliation(
                    reconciliation_id=(
                        "REC-" + hashlib.sha256(source_record_id.encode()).hexdigest()[:24].upper()
                    ),
                    source_record_id=source_record_id,
                )
                db.add(row)
            row.candidate_id = candidate_id or None
            row.recipient_email = ";".join(emails) or None
            row.classification = classification
            row.reason = reason
            row.evidence_json = json.dumps(
                evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            row.reconciled_at = datetime.now(UTC)
            results.append(
                {
                    "source_record_id": source_record_id,
                    "candidate_id": candidate_id,
                    "company": pipeline[2] or universe[1],
                    "recipient_email": ";".join(emails),
                    "classification": classification,
                    "reason": reason,
                    "evidence_sha256": hashlib.sha256(row.evidence_json.encode()).hexdigest(),
                }
            )
        db.commit()
    output_root = Path(os.getenv("PARTNERPOINT_RECONCILIATION_OUTPUT_DIR", "/app/runtime"))
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "partnerpoint-reconciliation-20260908.json"
    csv_path = output_root / "partnerpoint-reconciliation-20260908.csv"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(
        json.dumps(
            {
                "status": "RECONCILED",
                "count": len(results),
                "classifications": Counter(item["classification"] for item in results),
                "json_path": str(json_path),
                "csv_path": str(csv_path),
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
