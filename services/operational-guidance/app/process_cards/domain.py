from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.checklists.domain import ChecklistTemplate


class RealRole(str, Enum):
    UGYVEZETO = "Ügyvezető"
    MARKETINGES = "Marketinges"
    ERTEKESITO = "Értékesítő"
    PENZUGYES = "Pénzügyes"
    PROJEKTMENEDZSER = "Projektmenedzser"


FAMILY_ROLE_DEFAULTS: dict[str, RealRole] = {
    "GOV": RealRole.UGYVEZETO,
    "STR": RealRole.UGYVEZETO,
    "MKT": RealRole.MARKETINGES,
    "SAL": RealRole.ERTEKESITO,
    "CUS": RealRole.ERTEKESITO,
    "ENG": RealRole.PROJEKTMENEDZSER,
    "PRC": RealRole.PROJEKTMENEDZSER,
    "PRJ": RealRole.PROJEKTMENEDZSER,
    "QUA": RealRole.PROJEKTMENEDZSER,
    "HSE": RealRole.PROJEKTMENEDZSER,
    "FIN": RealRole.PENZUGYES,
    "HRA": RealRole.UGYVEZETO,
    "LEG": RealRole.UGYVEZETO,
    "DAT": RealRole.UGYVEZETO,
    "AST": RealRole.PROJEKTMENEDZSER,
    "BCM": RealRole.UGYVEZETO,
    "AUD": RealRole.UGYVEZETO,
    "KNW": RealRole.PROJEKTMENEDZSER,
    "INN": RealRole.UGYVEZETO,
}

ROLE_KEYWORDS: dict[RealRole, tuple[str, ...]] = {
    RealRole.UGYVEZETO: (
        "jóváhagy",
        "vezető",
        "stratég",
        "jogi",
        "hr",
        "szervezet",
        "döntés",
        "audit",
        "compliance",
    ),
    RealRole.MARKETINGES: (
        "marketing",
        "kampány",
        "hirdetés",
        "seo",
        "poszt",
        "tartalom",
        "attribúció",
    ),
    RealRole.ERTEKESITO: (
        "értékes",
        "ajánlat",
        "ügyfél",
        "lead",
        "crm",
        "szerződés előkész",
        "opportunity",
    ),
    RealRole.PENZUGYES: (
        "pénzügy",
        "számla",
        "fizetés",
        "cashflow",
        "könyvel",
        "költség",
        "utalás",
        "budget",
    ),
    RealRole.PROJEKTMENEDZSER: (
        "projekt",
        "kivitelez",
        "műszaki",
        "alvállalkoz",
        "ütemterv",
        "átadás",
        "hiba",
        "hse",
        "minőség",
    ),
}


def resolve_real_role(text: str | None, *, family: str | None = None) -> RealRole:
    value = text or ""
    found: list[tuple[int, RealRole]] = []
    for role in RealRole:
        position = value.casefold().find(role.value.casefold())
        if position >= 0:
            found.append((position, role))
    if found:
        return sorted(found, key=lambda item: item[0])[0][1]
    if family and family.upper() in FAMILY_ROLE_DEFAULTS:
        return FAMILY_ROLE_DEFAULTS[family.upper()]
    haystack = value.casefold()
    scores = {
        role: sum(haystack.count(keyword) for keyword in keywords)
        for role, keywords in ROLE_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else RealRole.UGYVEZETO


def extract_real_role_participants(text: str | None, primary: RealRole) -> list[str]:
    value = (text or "").casefold()
    return [
        role.value
        for role in RealRole
        if role != primary and role.value.casefold() in value
    ]


@dataclass(slots=True)
class ProcessSource:
    process_key: str
    title: str
    trigger: str
    inputs: list[str]
    steps: list[str]
    outputs: list[str]
    stop_conditions: list[str]
    completion_conditions: list[str]
    source_role: str | None = None
    policy_refs: list[str] = field(default_factory=list)
    source_updated_at: str | None = None
    family: str | None = None
    gate_id: str | None = None
    checklist_template_id: str | None = None
    object_type: str = "BusinessObject"
    participant_roles: list[str] = field(default_factory=list)
    external_participants: list[str] = field(default_factory=list)
    approval_role: str | None = None
    checklist_required: bool = False
    source_version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def checksum(self) -> str:
        payload = asdict(self)
        payload.pop("source_updated_at", None)
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class HumanProcessCard:
    process_key: str
    title: str
    role: RealRole
    when_to_do: str
    receive: list[str]
    handover: list[str]
    steps: list[str]
    stop_conditions: list[str]
    done_when: list[str]
    policy_refs: list[str]
    source_checksum: str
    family: str | None = None
    gate_id: str | None = None
    checklist_template_id: str | None = None
    checklist_version: str | None = None
    object_type: str = "BusinessObject"
    participant_roles: list[str] = field(default_factory=list)
    external_participants: list[str] = field(default_factory=list)
    approval_role: str | None = None
    version: int = 1
    status: str = "draft"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    approved_at: str | None = None
    approved_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["role"] = self.role.value
        return data


def assign_real_role(source: ProcessSource) -> RealRole:
    explicit = resolve_real_role(source.source_role, family=source.family)
    if source.source_role or source.family:
        return explicit
    haystack = " ".join(
        [source.title, source.trigger, *source.steps, *source.outputs]
    ).casefold()
    scores = {
        role: sum(haystack.count(keyword) for keyword in keywords)
        for role, keywords in ROLE_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else RealRole.UGYVEZETO


def _humanize(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .")
    replacements = {
        "validálja": "ellenőrizd",
        "validálni": "ellenőrizni",
        "rögzítésre kerül": "rögzítsd",
        "végrehajtandó": "végezd el",
        "implementálja": "vezesd be",
        "eszkalálja": "jelezd az ügyvezetőnek",
        "handover": "átadás",
        "workflow": "folyamat",
        "input": "bemenet",
        "output": "eredmény",
    }
    lowered = text.casefold()
    for old, new in replacements.items():
        if old in lowered:
            text = re.sub(old, new, text, flags=re.IGNORECASE)
            lowered = text.casefold()
    if text and text[-1] not in ".!?":
        text += "."
    return text[0].upper() + text[1:] if text else text


def composite_checksum(source: ProcessSource, checklist: ChecklistTemplate | None = None) -> str:
    parts = [source.checksum()]
    if checklist:
        parts.append(checklist.content_checksum())
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def build_human_card(
    source: ProcessSource,
    version: int = 1,
    checklist: ChecklistTemplate | None = None,
) -> HumanProcessCard:
    role = assign_real_role(source)
    steps = [_humanize(step) for step in source.steps if step.strip()]
    if not steps:
        steps = ["Ellenőrizd a feladat bemeneteit és jelezd, ha valami hiányzik."]
    checklist_id = source.checklist_template_id
    checklist_version = None
    if checklist:
        checklist_id = checklist.template_id
        checklist_version = checklist.version
    participants = list(dict.fromkeys([
        *source.participant_roles,
        *extract_real_role_participants(source.source_role, role),
    ]))
    return HumanProcessCard(
        process_key=source.process_key,
        title=source.title,
        role=role,
        when_to_do=_humanize(source.trigger),
        receive=[_humanize(item) for item in source.inputs],
        handover=[_humanize(item) for item in source.outputs],
        steps=steps,
        stop_conditions=[_humanize(item) for item in source.stop_conditions],
        done_when=[_humanize(item) for item in source.completion_conditions],
        policy_refs=source.policy_refs,
        source_checksum=composite_checksum(source, checklist),
        family=source.family,
        gate_id=source.gate_id or (checklist.gate_id if checklist else None),
        checklist_template_id=checklist_id,
        checklist_version=checklist_version,
        object_type=source.object_type,
        participant_roles=participants,
        external_participants=source.external_participants,
        approval_role=source.approval_role,
        version=version,
    )
