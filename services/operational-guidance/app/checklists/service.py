from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from functools import wraps
from pathlib import Path
from typing import Any

from app.checklists.domain import (
    ChecklistAnswer,
    ChecklistInstance,
    ChecklistInstanceItem,
    ChecklistInstanceStatus,
    ChecklistTemplate,
    utcnow_iso,
)
from app.checklists.render import render_instance_pdf, render_png, render_template_pdf
from app.checklists.store import JsonChecklistStore
from app.operations.adapters import NullOperationalRecordSink, OperationalRecordSink
from app.process_cards.domain import RealRole


class ChecklistValidationError(ValueError):
    pass


def _instance_locked(method):
    @wraps(method)
    def wrapped(self, instance_id: str, *args, **kwargs):
        with self.store.instance_lock(instance_id):
            return method(self, instance_id, *args, **kwargs)

    return wrapped


class ChecklistEngine:
    def __init__(
        self,
        runtime_root: Path,
        record_sink: OperationalRecordSink | None = None,
    ):
        self.runtime_root = runtime_root
        self.store = JsonChecklistStore(runtime_root)
        self.record_sink = record_sink or NullOperationalRecordSink()
        self.artifacts = runtime_root / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def import_catalog(
        self,
        catalog: dict[str, Any] | Path,
        *,
        persist: bool = True,
    ) -> dict[str, int]:
        if isinstance(catalog, Path):
            payload = json.loads(catalog.read_text(encoding="utf-8"))
        else:
            payload = catalog
        imported = 0
        unchanged = 0
        for item in payload.get("checklist_templates") or []:
            template = ChecklistTemplate.from_dict(item)
            template.checksum = template.content_checksum()
            try:
                existing = self.store.load_template(template.template_id, template.version)
            except FileNotFoundError:
                existing = None
            if existing and existing.content_checksum() == template.content_checksum():
                unchanged += 1
                continue
            self.store.save_template(template)
            if persist:
                self.record_sink.upsert_checklist_template(template.to_dict())
            imported += 1
        self.store.audit("checklist_catalog_imported", {"imported": imported, "unchanged": unchanged})
        return {"imported": imported, "unchanged": unchanged, "total": imported + unchanged}

    def template_for_process(
        self,
        process_key: str,
        *,
        approved_only: bool = False,
    ) -> ChecklistTemplate | None:
        return self.store.template_for_process(process_key, approved_only=approved_only)

    def render_template(self, template: ChecklistTemplate, output_dir: Path) -> dict[str, str]:
        pdf = render_template_pdf(template, output_dir / f"{template.template_id}_v{template.version}.pdf")
        png = render_png(pdf, output_dir / f"{template.template_id}_v{template.version}.png")
        return {"checklist_pdf": str(pdf), "checklist_png": str(png)}

    def approve_template(self, template_id: str, version: str, approved_by: str) -> ChecklistTemplate:
        template = self.store.approve_template(template_id, version, approved_by)
        self.record_sink.upsert_checklist_template(template.to_dict())
        return template

    def start_instance(
        self,
        process_key: str,
        object_id: str,
        created_by: str,
        *,
        object_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ChecklistInstance:
        request_payload = {
            "process_key": process_key,
            "object_id": object_id,
            "created_by": created_by,
            "object_type": object_type,
            "metadata": metadata or {},
        }
        request_hash = hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if idempotency_key:
            scope = "checklist-start"
            with self.store.idempotency_lock(scope, idempotency_key):
                existing = self.store.load_idempotency(scope, idempotency_key)
                if existing:
                    if existing.get("request_hash") != request_hash:
                        raise ChecklistValidationError(
                            "Az idempotency kulcs már más kéréshez lett felhasználva."
                        )
                    instance = self.store.load_instance(str(existing["instance_id"]))
                    self.record_sink.upsert_checklist_instance(instance.to_dict())
                    return instance
                instance = self._create_instance(
                    process_key,
                    object_id,
                    created_by,
                    object_type=object_type,
                    metadata=metadata,
                )
                self.store.save_idempotency(
                    scope,
                    idempotency_key,
                    {
                        "request_hash": request_hash,
                        "instance_id": instance.instance_id,
                        "created_at": instance.created_at,
                    },
                )
                self.record_sink.upsert_checklist_instance(instance.to_dict())
                return instance
        instance = self._create_instance(
            process_key,
            object_id,
            created_by,
            object_type=object_type,
            metadata=metadata,
        )
        self.record_sink.upsert_checklist_instance(instance.to_dict())
        return instance

    def _create_instance(
        self,
        process_key: str,
        object_id: str,
        created_by: str,
        *,
        object_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChecklistInstance:
        template = self.template_for_process(process_key, approved_only=True)
        if template is None:
            raise ChecklistValidationError(
                f"Nincs jóváhagyott checklist-sablon ehhez a folyamathoz: {process_key}"
            )
        instance_id = f"CLI-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:10].upper()}"
        instance = ChecklistInstance(
            instance_id=instance_id,
            template_id=template.template_id,
            template_version=template.version,
            process_key=process_key,
            gate_id=template.gate_id,
            role=template.primary_role,
            object_id=object_id,
            object_type=object_type or template.object_type,
            created_by=created_by,
            items=[
                ChecklistInstanceItem(
                    item_id=item.item_id,
                    text=item.text,
                    required=item.required,
                    blocking=item.blocking,
                    evidence_required=item.evidence_required,
                )
                for item in template.items
            ],
            metadata=metadata or {},
        )
        self.store.save_instance(instance)
        self.store.audit("checklist_instance_started", instance.to_dict())
        return instance

    @_instance_locked
    def answer_item(
        self,
        instance_id: str,
        item_id: str,
        answer: ChecklistAnswer | str,
        *,
        answered_by: str,
        note: str | None = None,
        evidence_ids: list[str] | None = None,
        action_owner_role: RealRole | str | None = None,
        action_due_date: str | None = None,
    ) -> ChecklistInstance:
        instance = self.store.load_instance(instance_id)
        if instance.status in {ChecklistInstanceStatus.APPROVED, ChecklistInstanceStatus.CLOSED}:
            raise ChecklistValidationError("A lezárt checklist nem módosítható.")
        parsed_answer = answer if isinstance(answer, ChecklistAnswer) else ChecklistAnswer(answer)
        item = next((candidate for candidate in instance.items if candidate.item_id == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if parsed_answer == ChecklistAnswer.NO:
            if not (note or "").strip():
                raise ChecklistValidationError("NEM válasznál kötelező a megjegyzés.")
            if not action_owner_role or not action_due_date:
                raise ChecklistValidationError(
                    "NEM válasznál kötelező a felelős munkakör és a határidő."
                )
        if parsed_answer == ChecklistAnswer.NA and not (note or "").strip():
            raise ChecklistValidationError("N.A. válasznál kötelező az indoklás.")
        role = None
        if action_owner_role:
            role = action_owner_role if isinstance(action_owner_role, RealRole) else RealRole(action_owner_role)
        item.answer = parsed_answer
        item.note = note
        item.evidence_ids = list(dict.fromkeys(evidence_ids or []))
        item.action_owner_role = role
        item.action_due_date = action_due_date
        item.answered_by = answered_by
        item.answered_at = utcnow_iso()
        instance.evaluate_status()
        self.store.save_instance(instance)
        self.record_sink.upsert_checklist_instance(instance.to_dict())
        self.store.audit("checklist_item_answered", {"instance_id": instance_id, "item": item.to_dict(), "status": instance.status.value})
        return instance

    @_instance_locked
    def add_evidence(self, instance_id: str, evidence_ids: list[str]) -> ChecklistInstance:
        instance = self.store.load_instance(instance_id)
        instance.evidence_ids = list(dict.fromkeys([*instance.evidence_ids, *evidence_ids]))
        instance.updated_at = utcnow_iso()
        self.store.save_instance(instance)
        self.record_sink.upsert_checklist_instance(instance.to_dict())
        self.store.audit("checklist_evidence_added", {"instance_id": instance_id, "evidence_ids": evidence_ids})
        return instance

    @_instance_locked
    def submit(self, instance_id: str, submitted_by: str) -> dict[str, Any]:
        instance = self.store.load_instance(instance_id)
        template = self.store.load_template(instance.template_id, instance.template_version)
        if instance.unanswered_required():
            raise ChecklistValidationError("Minden kötelező checklistpontot ki kell tölteni.")
        if instance.blocking_failures():
            instance.status = ChecklistInstanceStatus.HOLD
            instance.updated_at = utcnow_iso()
            self.store.save_instance(instance)
            self.record_sink.upsert_checklist_instance(instance.to_dict())
            raise ChecklistValidationError(
                "Blocking NEM válasz miatt a folyamat HOLD állapotban van."
            )
        if template.required_evidence and not instance.evidence_ids:
            raise ChecklistValidationError("A lezáráshoz kötelező bizonyítékot csatolni.")
        missing_item_evidence = [
            item.item_id
            for item in instance.items
            if item.evidence_required and item.answer == ChecklistAnswer.YES and not item.evidence_ids and not instance.evidence_ids
        ]
        if missing_item_evidence:
            raise ChecklistValidationError(
                "Bizonyíték hiányzik ezekhez a pontokhoz: " + ", ".join(missing_item_evidence)
            )
        instance.status = ChecklistInstanceStatus.READY_FOR_APPROVAL
        instance.submitted_at = utcnow_iso()
        instance.updated_at = instance.submitted_at
        instance.metadata["submitted_by"] = submitted_by
        self.store.save_instance(instance)
        self.record_sink.upsert_checklist_instance(instance.to_dict())
        queue = self.store.queue_instance_for_approval(instance)
        out_dir = self.artifacts / instance.instance_id
        pdf = render_instance_pdf(instance, template, out_dir / f"{instance.instance_id}.pdf")
        png = render_png(pdf, out_dir / f"{instance.instance_id}.png")
        return {"instance": instance.to_dict(), "approval_record": str(queue), "artifacts": {"pdf": str(pdf), "png": str(png)}}

    @_instance_locked
    def approve_instance(self, instance_id: str, approved_by: str) -> dict[str, Any]:
        instance = self.store.load_instance(instance_id)
        if instance.status != ChecklistInstanceStatus.READY_FOR_APPROVAL:
            raise ChecklistValidationError("Csak jóváhagyásra kész checklist hagyható jóvá.")
        template = self.store.load_template(instance.template_id, instance.template_version)
        instance.status = ChecklistInstanceStatus.APPROVED
        instance.approved_by = approved_by
        instance.approved_at = utcnow_iso()
        instance.closed_at = instance.approved_at
        instance.status = ChecklistInstanceStatus.CLOSED
        instance.updated_at = instance.approved_at
        self.store.save_instance(instance)
        self.record_sink.upsert_checklist_instance(instance.to_dict())
        queue = self.store.instance_approval_dir / f"{instance.instance_id}.json"
        if queue.exists():
            queue.unlink()
        out_dir = self.artifacts / instance.instance_id
        pdf = render_instance_pdf(instance, template, out_dir / f"{instance.instance_id}_approved.pdf")
        png = render_png(pdf, out_dir / f"{instance.instance_id}_approved.png")
        self.store.audit("checklist_instance_approved", instance.to_dict())
        return {"instance": instance.to_dict(), "artifacts": {"pdf": str(pdf), "png": str(png)}}

    def gate_status(self, instance_id: str) -> dict[str, Any]:
        instance = self.store.load_instance(instance_id)
        blockers = [item.item_id for item in instance.blocking_failures()]
        unanswered = [item.item_id for item in instance.unanswered_required()]
        can_proceed = instance.status == ChecklistInstanceStatus.CLOSED
        return {
            "instance_id": instance_id,
            "gate_id": instance.gate_id,
            "status": instance.status.value,
            "can_proceed": can_proceed,
            "blocking_items": blockers,
            "unanswered_items": unanswered,
        }
