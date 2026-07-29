from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.checklists.domain import ChecklistInstance, ChecklistTemplate
from app.file_lock import exclusive_file_lock


def _version_key(value: str) -> tuple[int, ...]:
    numbers = [int(part) for part in re.findall(r"\d+", value)]
    return tuple(numbers or [0])


class JsonChecklistStore:
    """Audit-friendly reference store; Directus/PostgreSQL can replace it in production."""

    def __init__(self, root: Path):
        self.root = root
        self.templates_dir = root / "templates"
        self.instances_dir = root / "instances"
        self.template_approval_dir = root / "template_approval_queue"
        self.instance_approval_dir = root / "instance_approval_queue"
        self.locks_dir = root / "locks"
        self.idempotency_dir = root / "idempotency"
        self.audit_file = root / "audit.jsonl"
        for path in (
            self.templates_dir,
            self.instances_dir,
            self.template_approval_dir,
            self.instance_approval_dir,
            self.locks_dir,
            self.idempotency_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the same-directory atomic write without repeating a potentially
        # long, hash-based destination name. The shorter temporary name also
        # stays below the legacy Windows MAX_PATH boundary.
        temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @contextmanager
    def instance_lock(self, instance_id: str):
        lock_path = self.locks_dir / f"{instance_id}.lock"
        with exclusive_file_lock(lock_path):
            yield


    @staticmethod
    def _idempotency_name(scope: str, key: str) -> str:
        return hashlib.sha256(f"{scope}|{key}".encode()).hexdigest()

    @contextmanager
    def idempotency_lock(self, scope: str, key: str):
        name = self._idempotency_name(scope, key)
        lock_path = self.locks_dir / f"idempotency-{name}.lock"
        with exclusive_file_lock(lock_path):
            yield

    def load_idempotency(self, scope: str, key: str) -> dict[str, Any] | None:
        path = self.idempotency_dir / f"{self._idempotency_name(scope, key)}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_idempotency(self, scope: str, key: str, payload: dict[str, Any]) -> Path:
        path = self.idempotency_dir / f"{self._idempotency_name(scope, key)}.json"
        self._write_json(path, payload)
        return path

    def save_template(self, template: ChecklistTemplate) -> Path:
        path = self.templates_dir / f"{template.template_id}_v{template.version}.json"
        self._write_json(path, template.to_dict())
        return path

    def load_template(self, template_id: str, version: str | None = None) -> ChecklistTemplate:
        if version:
            path = self.templates_dir / f"{template_id}_v{version}.json"
        else:
            matches = sorted(self.templates_dir.glob(f"{template_id}_v*.json"))
            if not matches:
                raise FileNotFoundError(template_id)
            path = matches[-1]
        return ChecklistTemplate.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def template_for_process(
        self,
        process_key: str,
        *,
        approved_only: bool = False,
    ) -> ChecklistTemplate | None:
        matches: list[ChecklistTemplate] = []
        for path in self.templates_dir.glob("*.json"):
            template = ChecklistTemplate.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if template.process_key != process_key:
                continue
            if approved_only and template.status != "approved":
                continue
            matches.append(template)
        if not matches:
            return None
        return sorted(matches, key=lambda item: _version_key(item.version))[-1]

    def list_templates(self) -> list[ChecklistTemplate]:
        latest: dict[str, ChecklistTemplate] = {}
        for path in self.templates_dir.glob("*.json"):
            template = ChecklistTemplate.from_dict(json.loads(path.read_text(encoding="utf-8")))
            current = latest.get(template.template_id)
            if current is None or _version_key(current.version) < _version_key(template.version):
                latest[template.template_id] = template
        return sorted(latest.values(), key=lambda item: item.template_id)

    def approve_template(self, template_id: str, version: str, approved_by: str) -> ChecklistTemplate:
        from app.checklists.domain import ChecklistTemplateStatus, utcnow_iso

        template = self.load_template(template_id, version)
        template.status = ChecklistTemplateStatus.APPROVED.value
        template.approved_by = approved_by
        template.approved_at = utcnow_iso()
        self.save_template(template)
        queue = self.template_approval_dir / f"{template_id}_v{version}.json"
        if queue.exists():
            queue.unlink()
        self.audit("checklist_template_approved", template.to_dict())
        return template

    def queue_template_for_approval(
        self, template: ChecklistTemplate, artifacts: dict[str, str]
    ) -> Path:
        payload = template.to_dict() | {"artifacts": artifacts}
        path = self.template_approval_dir / f"{template.template_id}_v{template.version}.json"
        self._write_json(path, payload)
        self.audit("checklist_template_queued", payload)
        return path

    def save_instance(self, instance: ChecklistInstance) -> Path:
        path = self.instances_dir / f"{instance.instance_id}.json"
        self._write_json(path, instance.to_dict())
        return path

    def load_instance(self, instance_id: str) -> ChecklistInstance:
        path = self.instances_dir / f"{instance_id}.json"
        return ChecklistInstance.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def queue_instance_for_approval(self, instance: ChecklistInstance) -> Path:
        path = self.instance_approval_dir / f"{instance.instance_id}.json"
        self._write_json(path, instance.to_dict())
        self.audit("checklist_instance_submitted", instance.to_dict())
        return path

    def audit(self, event: str, payload: dict[str, Any]) -> None:
        from app.checklists.domain import utcnow_iso

        record = {"at": utcnow_iso(), "event": event, "payload": payload}
        with self.audit_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
