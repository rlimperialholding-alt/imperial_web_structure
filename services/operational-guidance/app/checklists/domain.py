from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.process_cards.domain import RealRole, resolve_real_role


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class ChecklistAnswer(str, Enum):
    YES = "IGEN"
    NO = "NEM"
    NA = "N.A."


class ChecklistTemplateStatus(str, Enum):
    DRAFT = "draft"
    UAT = "uat"
    APPROVED = "approved"
    ARCHIVED = "archived"


class ChecklistInstanceStatus(str, Enum):
    OPEN = "open"
    HOLD = "hold"
    READY_FOR_APPROVAL = "ready_for_approval"
    APPROVED = "approved"
    CLOSED = "closed"


@dataclass(slots=True)
class ChecklistTemplateItem:
    item_id: str
    text: str
    required: bool = True
    blocking: bool = True
    evidence_required: bool = False


@dataclass(slots=True)
class ChecklistTemplate:
    template_id: str
    process_key: str
    title: str
    family: str
    primary_role: RealRole
    when_to_use: str
    gate_id: str
    object_type: str
    items: list[ChecklistTemplateItem]
    stop_conditions: list[str]
    required_evidence: list[str]
    closer_approver: str
    answer_mode: str = "IGEN / NEM / N.A."
    version: str = "1.0"
    status: str = ChecklistTemplateStatus.DRAFT.value
    source_url: str = ""
    participant_roles: list[str] = field(default_factory=list)
    external_participants: list[str] = field(default_factory=list)
    checksum: str = ""
    approved_at: str | None = None
    approved_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChecklistTemplate:
        data = dict(payload)
        data["primary_role"] = resolve_real_role(
            str(data.get("primary_role") or ""), family=str(data.get("family") or "")
        )
        data["items"] = [
            item if isinstance(item, ChecklistTemplateItem) else ChecklistTemplateItem(**item)
            for item in data.get("items") or []
        ]
        return cls(**data)

    def content_checksum(self) -> str:
        data = self.to_dict()
        for key in ("checksum", "approved_at", "approved_by", "status"):
            data.pop(key, None)
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["primary_role"] = self.primary_role.value
        return data


@dataclass(slots=True)
class ChecklistInstanceItem:
    item_id: str
    text: str
    required: bool
    blocking: bool
    evidence_required: bool
    answer: ChecklistAnswer | None = None
    note: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    action_owner_role: RealRole | None = None
    action_due_date: str | None = None
    answered_by: str | None = None
    answered_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChecklistInstanceItem:
        data = dict(payload)
        if data.get("answer"):
            data["answer"] = ChecklistAnswer(data["answer"])
        if data.get("action_owner_role"):
            data["action_owner_role"] = RealRole(data["action_owner_role"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["answer"] = self.answer.value if self.answer else None
        data["action_owner_role"] = (
            self.action_owner_role.value if self.action_owner_role else None
        )
        return data


@dataclass(slots=True)
class ChecklistInstance:
    instance_id: str
    template_id: str
    template_version: str
    process_key: str
    gate_id: str
    role: RealRole
    object_id: str
    object_type: str
    created_by: str
    items: list[ChecklistInstanceItem]
    status: ChecklistInstanceStatus = ChecklistInstanceStatus.OPEN
    evidence_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    submitted_at: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None
    closed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChecklistInstance:
        data = dict(payload)
        data["role"] = RealRole(data["role"])
        data["status"] = ChecklistInstanceStatus(data["status"])
        data["items"] = [ChecklistInstanceItem.from_dict(item) for item in data["items"]]
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["role"] = self.role.value
        data["status"] = self.status.value
        data["items"] = [item.to_dict() for item in self.items]
        return data

    def blocking_failures(self) -> list[ChecklistInstanceItem]:
        return [item for item in self.items if item.blocking and item.answer == ChecklistAnswer.NO]

    def unanswered_required(self) -> list[ChecklistInstanceItem]:
        return [item for item in self.items if item.required and item.answer is None]

    def evaluate_status(self) -> ChecklistInstanceStatus:
        if self.blocking_failures():
            self.status = ChecklistInstanceStatus.HOLD
        elif self.unanswered_required():
            self.status = ChecklistInstanceStatus.OPEN
        elif self.status not in {
            ChecklistInstanceStatus.APPROVED,
            ChecklistInstanceStatus.CLOSED,
        }:
            self.status = ChecklistInstanceStatus.READY_FOR_APPROVAL
        self.updated_at = utcnow_iso()
        return self.status
