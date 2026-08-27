from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from typing import Any

from app.file_lock import exclusive_file_lock
from app.process_cards.domain import HumanProcessCard, ProcessSource, RealRole


class JsonProcessCardStore:
    """File-backed reference implementation; production can replace it with PostgreSQL/Directus."""

    def __init__(self, root: Path):
        self.root = root
        self.sources_dir = root / "sources"
        self.cards_dir = root / "cards"
        self.approval_dir = root / "approval_queue"
        self.locks_dir = root / "locks"
        self.audit_file = root / "audit.jsonl"
        for directory in (
            self.sources_dir,
            self.cards_dir,
            self.approval_dir,
            self.locks_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the same-directory atomic write without repeating a potentially
        # long destination name in the temporary filename.
        temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @contextmanager
    def process_lock(self, process_key: str):
        lock_path = self.locks_dir / f"{process_key}.lock"
        with exclusive_file_lock(lock_path):
            yield

    def save_source(self, source: ProcessSource) -> None:
        self._write_json(
            self.sources_dir / f"{source.process_key}.json",
            asdict(source),
        )

    def load_source(self, process_key: str) -> ProcessSource:
        return ProcessSource(**json.loads((self.sources_dir / f"{process_key}.json").read_text(encoding="utf-8")))

    def latest_card(self, process_key: str) -> HumanProcessCard | None:
        versions = sorted(self.cards_dir.glob(f"{process_key}_v*.json"))
        if not versions:
            return None
        data = json.loads(versions[-1].read_text(encoding="utf-8"))
        data["role"] = RealRole(data["role"])
        return HumanProcessCard(**data)

    def save_card(self, card: HumanProcessCard) -> Path:
        path = self.cards_dir / f"{card.process_key}_v{card.version:03d}.json"
        self._write_json(path, card.to_dict())
        return path

    def queue_for_approval(self, card: HumanProcessCard, artifacts: dict[str, str]) -> Path:
        payload: dict[str, Any] = card.to_dict() | {
            "artifacts": artifacts,
            "notification": {"status": "pending"},
        }
        path = self.approval_dir / f"{card.process_key}_v{card.version:03d}.json"
        self._write_json(path, payload)
        self.audit("queued_for_approval", payload)
        return path


    def mark_approval_notification(
        self,
        process_key: str,
        version: int,
        *,
        status: str,
        notification_id: str | None = None,
        error: str | None = None,
    ) -> None:
        from datetime import datetime

        path = self.approval_dir / f"{process_key}_v{version:03d}.json"
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["notification"] = {
            "status": status,
            "notification_id": notification_id,
            "error": error,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self._write_json(path, payload)

    def pending_approval_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.approval_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("notification", {}).get("status") != "sent":
                records.append(payload)
        return records

    def approve(
        self,
        process_key: str,
        version: int,
        approved_by: str,
        *,
        approved_at: str | None = None,
    ) -> HumanProcessCard:
        path = self.cards_dir / f"{process_key}_v{version:03d}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "approved"
        from datetime import datetime
        data["approved_at"] = approved_at or datetime.now(UTC).isoformat()
        data["approved_by"] = approved_by
        self._write_json(path, data)
        queue = self.approval_dir / f"{process_key}_v{version:03d}.json"
        if queue.exists():
            queue.unlink()
        data["role"] = RealRole(data["role"])
        card = HumanProcessCard(**data)
        self.audit("approved", card.to_dict())
        return card

    def audit(self, event: str, payload: dict[str, Any]) -> None:
        from datetime import datetime
        record = {"at": datetime.now(UTC).isoformat(), "event": event, "payload": payload}
        with self.audit_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
