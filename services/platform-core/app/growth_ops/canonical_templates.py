from __future__ import annotations

import hashlib
import html
import json
import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .registry import GrowthRegistryError

DEFAULT_REGISTRY_PATH = (
    "/app/config/outbound/canonical_first_contact_templates_hu_v1.json"
)
REQUIRED_TEMPLATE_IDS = {
    "architect_office": "ARCHITECT_OFFICE_FIRST_CONTACT_HU",
    "land_owner": "LAND_OWNER_FIRST_CONTACT_HU",
    "real_estate_agent": "REAL_ESTATE_AGENT_FIRST_CONTACT_HU",
    "referral_partner": "REFERRAL_PARTNER_FIRST_CONTACT_HU",
}
OWNER_APPROVED = {"OWNER_APPROVED", "CANONICAL"}
LEGACY_REFERRAL_TEMPLATE_ID = "PARTNERPOINT_LEGACY_1_PERCENT_FIRST_CONTACT_HU"
EXPECTED_REGISTRY_SHA256 = "bd5f8f2f0d8419c9fbe9ca05a8a5501fc1a6fbd7cdbaacbd2ae719d1a116f6e7"
EXPECTED_SELECTION_PIPELINE = [
    "HARD_GATES",
    "RECIPIENT_CLASSIFICATION_VERIFIED",
    "EXCLUSION_SCREENING_VERIFIED",
    "REFERENCES_VERIFIED_OR_APPROVED_ZERO_REFERENCE_FALLBACK",
    "VERIFIED_BUSINESS_CONTEXT_REQUIRED_FOR_REFERRAL_PARTNER",
    "RECIPIENT_TYPE_EXACT_MATCH",
    "CANONICAL_TEMPLATE_RENDER",
]
EXPECTED_BRAND_ISOLATION_POLICY = {
    "customer_facing_brand_count": "EXACTLY_ONE",
    "cross_brand_decision": "NO_SEND",
    "rewrite_policy": "PROHIBITED",
    "sender_brands": {
        "imperial": {
            "required_company_name": "Imperial Holding",
            "required_identity_terms_any": ["Imperial"],
            "forbidden_customer_facing_terms": [
                "Prefab.hu",
                "Prefab",
                "Bautica",
                "Bautica.hu",
                "Casa Moderna",
                "CasaModerna",
                "Casa-Moderna",
                "casa-moderna.hu",
                "BauFreund",
                "Bau Freund",
                "Bau-Freund",
                "baufreund.hu",
                "Danish Fabrik",
                "DanishFabrik",
                "Danish-Fabrik",
                "danishfabrik.hu",
                "TimberHaus",
                "Timber Haus",
                "Timber-Haus",
                "timberhaus.hu",
                "RED Property",
                "REDProperty",
                "RED-Property",
                "Property360",
                "Property 360",
                "Property-360",
                "property360.hu",
                "Everyday Homes",
                "EverydayHomes",
                "Everyday-Homes",
                "everydayhomes.hu",
                "Venture Studio",
                "VentureStudio",
                "Venture-Studio",
                "venturestudio.hu",
                "Family Homes",
                "FamilyHomes",
                "Family-Homes",
                "familyhomes.hu",
                "Imperial Construction",
                "ImperialConstruction",
                "Imperial-Construction",
                "Budapesti Magasépítő Vállalat",
                "budapesti-magasepito-vallalat",
                "Imperial Intelligence",
                "ImperialIntelligence",
                "Imperial-Intelligence",
                "Imperial Technologies",
                "ImperialTechnologies",
                "Imperial-Technologies",
                "Imperial Knowledge",
                "ImperialKnowledge",
                "Imperial-Knowledge",
                "ExitFlow",
                "Exit Flow",
                "Exit-Flow",
                "exitflow.hu",
                "Veritas Construct",
                "VeritasConstruct",
                "Veritas-Construct",
                "veritasconstruct.hu",
                "Veritas",
                "BauShield",
                "Bau Shield",
                "Bau-Shield",
                "baushield.hu",
            ],
        }
    },
}
EXPECTED_HARD_GATES: list[dict[str, Any]] = [
    {
        "gate_id": "BLOCK_TURCZER_JOZSEF",
        "decision": "NO_SEND",
        "scope": "ALL_CONTACTS",
        "normalized_any": [
            "turczer jozsef",
            "jozsef turczer",
            "turczerjozsef",
            "jozsefturczer",
        ],
    },
    {
        "gate_id": "BLOCK_OTTHON_CENTRUM_BUDAPEST_II_IIA_XII",
        "decision": "NO_SEND",
        "scope": "OFFICES_AND_ALL_CONTACTS",
        "normalized_all_any": [
            ["otthon centrum", "oc ingatlan", "oc hu"],
            [
                "budapest ii kerulet",
                "budapest ii keruleti",
                "budapest ii",
                "ii kerulet",
                "ii keruleti",
                "ii",
                "2 kerulet",
                "2 keruleti",
                "budapest ii a kerulet",
                "budapest ii a keruleti",
                "budapest ii a",
                "ii a kerulet",
                "ii a keruleti",
                "ii a",
                "budapest iia kerulet",
                "budapest iia keruleti",
                "budapest iia",
                "iia kerulet",
                "iia keruleti",
                "iia",
                "budapest 2 a kerulet",
                "budapest 2 a keruleti",
                "budapest 2 a",
                "2 a kerulet",
                "2 a keruleti",
                "2 a",
                "budapest 2a kerulet",
                "budapest 2a keruleti",
                "budapest 2a",
                "2a kerulet",
                "2a keruleti",
                "2a",
                "budapest xii kerulet",
                "budapest xii keruleti",
                "budapest xii",
                "xii kerulet",
                "xii keruleti",
                "xii",
                "12 kerulet",
                "12 keruleti",
                "bem rakpart",
                "tdg",
                "hidegkuti ut",
                "lajos utca",
                "uromi utca",
                "mom park",
                "varosmajor utca",
                "1020",
                "1021",
                "1022",
                "1023",
                "1024",
                "1025",
                "1026",
                "1027",
                "1028",
                "1029",
                "1120",
                "1121",
                "1122",
                "1123",
                "1124",
                "1125",
                "1126",
                "1127",
                "1128",
                "1129",
            ],
        ],
    },
    {
        "gate_id": "BLOCK_GDN_INGATLANHALOZAT",
        "decision": "NO_SEND",
        "scope": "FULL_NETWORK_AND_ALL_CONTACTS",
        "normalized_word_any": ["gdn"],
        "normalized_any": ["gdn ingatlanhalozat", "gdn ingatlan", "g d n"],
    },
    {
        "gate_id": "BLOCK_LEIER_INCIDENT_CONTAINMENT",
        "decision": "NO_SEND",
        "scope": "FULL_ENTITY_DOMAINS_AND_ALL_CONTACTS_UNTIL_OWNER_CLEARANCE",
        "normalized_any": [
            "leier",
            "leier hungaria",
            "leierhungaria",
            "leier group",
            "leiergroup",
            "leier hu",
            "leier eu",
            "leier at",
            "info leier hu",
            "kpertekesites leier hu",
            "kurucz hajnalka",
        ],
    },
]
REQUIRED_HARD_GATE_CASES = {
    "BLOCK_TURCZER_JOZSEF": ["Turczer József"],
    "BLOCK_OTTHON_CENTRUM_BUDAPEST_II_IIA_XII": [
        "Otthon Centrum",
        "Budapest II. kerületi iroda",
    ],
    "BLOCK_GDN_INGATLANHALOZAT": ["GDN Ingatlanhálózat"],
    "BLOCK_LEIER_INCIDENT_CONTAINMENT": ["Leier Hungária", "info@leier.hu"],
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _normalize(value: object) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_like = "".join(
        char
        for char in decomposed
        if not unicodedata.combining(char) and unicodedata.category(char) != "Cf"
    )
    return " ".join(re.sub(r"[^0-9a-z]+", " ", ascii_like.casefold()).split())


def _replace_once(value: str, marker: str, replacement: str) -> str:
    if value.count(marker) != 1:
        raise GrowthRegistryError(f"Canonical marker count is not one: {marker}")
    return value.replace(marker, replacement, 1)


def _validated_text(value: object, *, field: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        raise GrowthRegistryError(f"Canonical render field is missing: {field}")
    return normalized


def _validated_https_url(value: object, *, field: str) -> str:
    result = str(value or "").strip()
    parsed = urlparse(result)
    if parsed.scheme != "https" or not parsed.hostname or any(char.isspace() for char in result):
        raise GrowthRegistryError(f"Canonical {field} must be an absolute HTTPS URL")
    return result


def _validated_unsubscribe_url(value: object) -> str:
    return _validated_https_url(value, field="unsubscribe URL")


@dataclass(frozen=True)
class RenderedFirstContact:
    template_id: str
    recipient_type: str
    sender_brand_id: str
    subject: str | None
    body_text: str
    body_html: str
    sendable: bool
    blocked_reasons: tuple[str, ...]
    registry_sha256: str
    owner_body_sha256: str
    render_input: dict[str, Any]

    def metadata(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "recipient_type": self.recipient_type,
            "sender_brand_id": self.sender_brand_id,
            "registry_sha256": self.registry_sha256,
            "owner_body_sha256": self.owner_body_sha256,
            "rendered_subject_sha256": _sha256_text(self.subject or ""),
            "rendered_body_text_sha256": _sha256_text(self.body_text),
            "rendered_body_html_sha256": _sha256_text(self.body_html),
            "body_html": self.body_html,
            "sendable": self.sendable,
            "blocked_reasons": list(self.blocked_reasons),
            "render_input": self.render_input,
        }


class CanonicalFirstContactRegistry:
    def __init__(self, raw: dict[str, Any], *, source_bytes: bytes, source_path: Path) -> None:
        self.raw = raw
        self.source_path = source_path
        self.source_sha256 = _sha256_bytes(source_bytes)
        templates = raw.get("templates")
        if not isinstance(templates, list):
            raise GrowthRegistryError("Canonical first-contact templates must be a list")
        self.templates_by_id = {
            str(item.get("template_id") or ""): item
            for item in templates
            if isinstance(item, dict)
        }
        self.templates_by_recipient_type = {
            str(item.get("recipient_type") or ""): item
            for item in templates
            if isinstance(item, dict)
        }
        self._validate()

    @classmethod
    def load(cls, path: str | Path | None = None) -> CanonicalFirstContactRegistry:
        source_path = Path(
            path
            or os.getenv("CANONICAL_FIRST_CONTACT_REGISTRY_FILE")
            or DEFAULT_REGISTRY_PATH
        )
        try:
            source_bytes = source_path.read_bytes()
            raw = json.loads(source_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GrowthRegistryError(
                "Canonical first-contact registry is unreadable"
            ) from exc
        if not isinstance(raw, dict):
            raise GrowthRegistryError("Canonical first-contact registry is not an object")
        return cls(raw, source_bytes=source_bytes, source_path=source_path)

    def _validate(self) -> None:
        if self.raw.get("schema_version") != "1.0" or self.raw.get("registry_version") != 4:
            raise GrowthRegistryError("Unsupported canonical first-contact registry version")
        if set(self.raw.get("status") or []) != OWNER_APPROVED:
            raise GrowthRegistryError("Canonical registry status is not OWNER_APPROVED/CANONICAL")
        if self.raw.get("origin") != "HUMAN_AUTHORED_LOCKED":
            raise GrowthRegistryError("Canonical registry origin is not HUMAN_AUTHORED_LOCKED")
        if self.raw.get("ai_modification_allowed") is not False:
            raise GrowthRegistryError("AI modification must be disabled for canonical templates")
        if self.raw.get("fallback_policy") != "PROHIBITED":
            raise GrowthRegistryError("Canonical fallback policy must be PROHIBITED")
        if self.raw.get("generic_copy_override_policy") != "PROHIBITED":
            raise GrowthRegistryError("Generic copy override policy must be PROHIBITED")
        brand_policy = self.raw.get("brand_isolation_policy")
        if not isinstance(brand_policy, dict):
            raise GrowthRegistryError("Canonical brand-isolation policy is missing")
        if brand_policy != EXPECTED_BRAND_ISOLATION_POLICY:
            raise GrowthRegistryError("Canonical brand-isolation policy changed")
        if list(self.raw.get("selection_pipeline") or []) != EXPECTED_SELECTION_PIPELINE:
            raise GrowthRegistryError("Canonical selection pipeline changed")
        if set(self.templates_by_id) != set(REQUIRED_TEMPLATE_IDS.values()):
            raise GrowthRegistryError("Exactly the four required canonical templates must exist")
        if set(self.templates_by_recipient_type) != set(REQUIRED_TEMPLATE_IDS):
            raise GrowthRegistryError("Canonical recipient_type mapping is incomplete")
        if len(self.templates_by_id) != 4 or len(self.templates_by_recipient_type) != 4:
            raise GrowthRegistryError("Canonical template IDs and recipient types must be unique")
        hard_gates = self.raw.get("hard_gates")
        if not isinstance(hard_gates, list):
            raise GrowthRegistryError("Canonical hard gates must be a list")
        if hard_gates != EXPECTED_HARD_GATES:
            raise GrowthRegistryError("Canonical hard-gate policy changed")
        gate_ids = {
            str(gate.get("gate_id") or "")
            for gate in hard_gates
            if isinstance(gate, dict) and gate.get("decision") == "NO_SEND"
        }
        if not set(REQUIRED_HARD_GATE_CASES).issubset(gate_ids):
            raise GrowthRegistryError("Required canonical hard gate is missing")
        for gate_id, screening_values in REQUIRED_HARD_GATE_CASES.items():
            if self.hard_gate_match(screening_values) != gate_id:
                raise GrowthRegistryError(f"Canonical hard gate is ineffective: {gate_id}")

        for recipient_type, template_id in REQUIRED_TEMPLATE_IDS.items():
            template = self.templates_by_id[template_id]
            if template is not self.templates_by_recipient_type[recipient_type]:
                raise GrowthRegistryError("Canonical template recipient mapping conflicts")
            if set(template.get("status") or []) != OWNER_APPROVED:
                raise GrowthRegistryError(
                    f"Template is not OWNER_APPROVED/CANONICAL: {template_id}"
                )
            if template.get("origin") != "HUMAN_AUTHORED_LOCKED":
                raise GrowthRegistryError(f"Template origin is not locked: {template_id}")
            if template.get("ai_modification_allowed") is not False:
                raise GrowthRegistryError(f"AI modification is enabled: {template_id}")
            if template.get("sender_brand_id") != "imperial":
                raise GrowthRegistryError(f"Canonical sender brand is not imperial: {template_id}")
            body = str(template.get("owner_approved_body_text") or "")
            body_bytes = body.encode("utf-8")
            if _sha256_bytes(body_bytes) != template.get(
                "owner_approved_body_text_sha256_utf8"
            ):
                raise GrowthRegistryError(f"Owner body hash mismatch: {template_id}")
            if len(body_bytes) != template.get("owner_approved_body_text_utf8_bytes"):
                raise GrowthRegistryError(f"Owner body byte length mismatch: {template_id}")
            subject = template.get("subject")
            if subject is None:
                if template.get("subject_status") != "OWNER_INPUT_REQUIRED_NO_FALLBACK":
                    raise GrowthRegistryError(f"Missing subject is not fail-closed: {template_id}")
                if template.get("subject_sha256_utf8") is not None:
                    raise GrowthRegistryError(f"Null subject must not have a hash: {template_id}")
            elif _sha256_text(str(subject)) != template.get("subject_sha256_utf8"):
                raise GrowthRegistryError(f"Subject hash mismatch: {template_id}")
            for sentence in (template.get("html_formatting") or {}).get(
                "bold_exact_sentences", []
            ):
                if body.count(str(sentence)) != 1:
                    raise GrowthRegistryError(
                        f"HTML bold sentence is not an exact unique body sentence: {template_id}"
                    )

        referral = self.templates_by_id["REFERRAL_PARTNER_FIRST_CONTACT_HU"]
        land_owner = self.templates_by_id["LAND_OWNER_FIRST_CONTACT_HU"]
        if set(land_owner.get("allowed_replacements") or []) != {
            "recipient_name",
            "listing_location",
            "listing_size",
            "listing_url",
            "unsubscribe_url",
        }:
            raise GrowthRegistryError("Land-owner replacement allowlist changed")
        for marker in (
            "[település]",
            "[méret]",
            "[hirdetés linkje]",
        ):
            if str(land_owner["owner_approved_body_text"]).count(marker) != 1:
                raise GrowthRegistryError(
                    f"Land-owner body marker count is not one: {marker}"
                )
        for marker in ("[település]", "[méret]"):
            if str(land_owner["subject"]).count(marker) != 1:
                raise GrowthRegistryError(
                    f"Land-owner subject marker count is not one: {marker}"
                )
        if referral.get("subject") != "együttműködés":
            raise GrowthRegistryError("Referral-partner subject is not the immutable owner text")
        if referral.get("subject_status") != "OWNER_APPROVED_IMMUTABLE":
            raise GrowthRegistryError("Referral-partner subject is not immutable")
        if referral.get("subject_immutable") is not True:
            raise GrowthRegistryError("Referral-partner subject mutability is not disabled")
        if referral.get("llm_rewrite_allowed") is not False:
            raise GrowthRegistryError("Referral-partner LLM rewriting is not disabled")
        if set(referral.get("allowed_replacements") or []) != {
            "recipient_name",
            "verified_business_context",
        }:
            raise GrowthRegistryError("Referral-partner replacement allowlist changed")
        if "\n\n\n" in str(referral["owner_approved_body_text"]):
            raise GrowthRegistryError("Referral-partner paragraph spacing is not canonical")
        if len(str(referral["owner_approved_body_text"]).split("\n\n")) != 5:
            raise GrowthRegistryError("Referral-partner paragraph count is not canonical")

        archived_templates = self.raw.get("archived_templates")
        if not isinstance(archived_templates, list):
            raise GrowthRegistryError("Canonical archived-template audit trail is missing")
        archived_by_id = {
            str(item.get("template_id") or ""): item
            for item in archived_templates
            if isinstance(item, dict)
        }
        legacy = archived_by_id.get(LEGACY_REFERRAL_TEMPLATE_ID)
        if not legacy:
            raise GrowthRegistryError("Legacy 1% PartnerPont audit record is missing")
        if legacy.get("active") is not False or set(legacy.get("status") or []) != {
            "ARCHIVED",
            "DEACTIVATED",
        }:
            raise GrowthRegistryError("Legacy 1% PartnerPont template is not deactivated")
        if legacy.get("fallback_allowed") is not False:
            raise GrowthRegistryError("Legacy 1% PartnerPont fallback remains enabled")
        if legacy.get("replaced_by") != "REFERRAL_PARTNER_FIRST_CONTACT_HU":
            raise GrowthRegistryError("Legacy 1% PartnerPont replacement audit is invalid")
        legacy_body = str(legacy.get("body_text") or "")
        legacy_bytes = legacy_body.encode("utf-8")
        if _sha256_bytes(legacy_bytes) != legacy.get("body_text_sha256_utf8"):
            raise GrowthRegistryError("Legacy 1% PartnerPont body hash mismatch")
        if len(legacy_bytes) != legacy.get("body_text_utf8_bytes"):
            raise GrowthRegistryError("Legacy 1% PartnerPont body byte length mismatch")
        if self.source_sha256 != EXPECTED_REGISTRY_SHA256:
            raise GrowthRegistryError("Canonical registry byte hash changed")

    def hard_gate_match(self, screening_values: Sequence[object]) -> str | None:
        normalized = _normalize("\n".join(str(value or "") for value in screening_values))
        padded = f" {normalized} "

        def contains_term(term: object) -> bool:
            normalized_term = _normalize(term)
            return bool(normalized_term) and f" {normalized_term} " in padded

        for gate in self.raw.get("hard_gates") or []:
            if not isinstance(gate, dict) or gate.get("decision") != "NO_SEND":
                raise GrowthRegistryError("Canonical hard gate is malformed")
            if any(contains_term(term) for term in gate.get("normalized_any") or []):
                return str(gate.get("gate_id"))
            if any(
                contains_term(term)
                for term in gate.get("normalized_word_any") or []
            ):
                return str(gate.get("gate_id"))
            groups = gate.get("normalized_all_any") or []
            if groups and all(
                any(contains_term(term) for term in group) for group in groups
            ):
                return str(gate.get("gate_id"))
        return None

    def _assert_brand_isolation(
        self, *, sender_brand_id: str, subject: str, body_text: str
    ) -> None:
        policy = (self.raw.get("brand_isolation_policy") or {}).get(
            "sender_brands", {}
        ).get(sender_brand_id)
        if not isinstance(policy, dict):
            raise GrowthRegistryError("canonical_sender_brand_isolation_missing_no_send")
        customer_facing_text = f"{subject}\n{body_text}"
        normalized = f" {_normalize(customer_facing_text)} "

        def contains(term: object) -> bool:
            normalized_term = _normalize(term)
            return bool(normalized_term) and f" {normalized_term} " in normalized

        forbidden = [
            str(term)
            for term in policy.get("forbidden_customer_facing_terms") or []
            if contains(term)
        ]
        if forbidden:
            raise GrowthRegistryError(
                "cross_brand_customer_facing_content_no_send:" + ",".join(forbidden)
            )
        if not any(contains(term) for term in policy.get("required_identity_terms_any") or []):
            raise GrowthRegistryError("canonical_sender_identity_missing_no_send")

    def _body_html(self, body_text: str, template: dict[str, Any]) -> str:
        escaped = html.escape(body_text)
        for sentence in (template.get("html_formatting") or {}).get(
            "bold_exact_sentences", []
        ):
            escaped_sentence = html.escape(str(sentence))
            if escaped.count(escaped_sentence) != 1:
                raise GrowthRegistryError("Rendered bold sentence integrity check failed")
            escaped = escaped.replace(
                escaped_sentence, f"<strong>{escaped_sentence}</strong>", 1
            )
        return "".join(
            f"<p>{paragraph.replace(chr(10), '<br>')}</p>"
            for paragraph in escaped.split("\n\n")
        )

    def render(
        self,
        *,
        recipient_type: str,
        recipient_name: str | None,
        sender_company_name: str | None,
        reference_names: list[str] | tuple[str, ...] | None,
        reference_names_verified: bool,
        business_context: str | None,
        business_context_verified: bool,
        business_context_evidence_url: str | None,
        listing_location: str | None = None,
        listing_size: str | None = None,
        listing_url: str | None = None,
        unsubscribe_url: str | None,
        recipient_classification_verified: bool,
        exclusion_screening_verified: bool,
        screening_values: list[object],
    ) -> RenderedFirstContact:
        render_input = {
            "recipient_type": recipient_type,
            "recipient_name": recipient_name,
            "sender_company_name": sender_company_name,
            "reference_names": list(reference_names or []),
            "reference_names_verified": reference_names_verified,
            "business_context": business_context,
            "business_context_verified": business_context_verified,
            "business_context_evidence_url": business_context_evidence_url,
            "listing_location": listing_location,
            "listing_size": listing_size,
            "listing_url": listing_url,
            "unsubscribe_url": unsubscribe_url,
            "recipient_classification_verified": recipient_classification_verified,
            "exclusion_screening_verified": exclusion_screening_verified,
            "screening_values": [str(value or "") for value in screening_values],
        }
        if not recipient_classification_verified:
            raise GrowthRegistryError("recipient_classification_not_verified_no_send")
        if not exclusion_screening_verified:
            raise GrowthRegistryError("exclusion_screening_not_verified_no_send")
        hard_gate = self.hard_gate_match(screening_values)
        if hard_gate:
            raise GrowthRegistryError(f"canonical_hard_gate_blocked:{hard_gate}")
        template = self.templates_by_recipient_type.get(recipient_type)
        if not template:
            raise GrowthRegistryError("recipient_type_unknown_or_unsupported_no_send")

        body = str(template["owner_approved_body_text"])
        name = _validated_text(recipient_name, field="recipient_name")
        if recipient_type == "architect_office":
            sender = _validated_text(sender_company_name, field="sender_company_name")
            expected_sender = str(
                self.raw["brand_isolation_policy"]["sender_brands"][
                    str(template["sender_brand_id"])
                ]["required_company_name"]
            )
            if _normalize(sender) != _normalize(expected_sender):
                raise GrowthRegistryError(
                    "canonical_sender_company_conflicts_with_sender_brand_no_send"
                )
            references = [
                _validated_text(item, field="reference_names") for item in reference_names or []
            ]
            if len(references) not in {0, 2, 3}:
                raise GrowthRegistryError("architect_reference_count_must_be_zero_two_or_three")
            if references and not reference_names_verified:
                raise GrowthRegistryError("architect_references_not_verified_no_send")
            body = _replace_once(body, "Tisztelt XY!", f"Tisztelt {name}!")
            if references:
                body = _replace_once(body, "(XY, CC, ZZ)", f"({', '.join(references)})")
            else:
                opening = (
                    "Azért kerestük fel az Ön irodáját, mert láttuk munkáit "
                    "(XY, CC, ZZ), és szeretnénk Önnel együttműködni."
                )
                fallback = str(template["reference_policy"]["zero_reference_opening_sentence"])
                body = _replace_once(body, opening, fallback)
            body = _replace_once(body, "Cégünk, az XY 1989", f"Cégünk, az {sender} 1989")
        elif recipient_type == "land_owner":
            location = _validated_text(listing_location, field="listing_location")
            size = _validated_text(listing_size, field="listing_size")
            if not re.fullmatch(r"[1-9][0-9]{0,7}(?:[.,][0-9]+)? m²", size):
                raise GrowthRegistryError("Canonical listing_size is invalid")
            url = _validated_https_url(listing_url, field="listing URL")
            body = _replace_once(body, "[Név]", name)
            body = _replace_once(body, "[település]", location)
            body = _replace_once(body, "[méret]", size)
            body = _replace_once(body, "[hirdetés linkje]", url)
            body = _replace_once(
                body,
                "[egyedi leiratkozási link]",
                _validated_unsubscribe_url(unsubscribe_url),
            )
        elif recipient_type == "real_estate_agent":
            body = _replace_once(body, "[Név]", name)
            body = _replace_once(
                body,
                "[egyedi leiratkozási link]",
                _validated_unsubscribe_url(unsubscribe_url),
            )
        elif recipient_type == "referral_partner":
            if not (
                business_context
                and business_context_verified
                and business_context_evidence_url
            ):
                raise GrowthRegistryError("template-variable-missing:business_context")
            _validated_https_url(
                business_context_evidence_url,
                field="business-context evidence URL",
            )
            body = _replace_once(body, "[Név]", name)
            body = _replace_once(
                body,
                "[konkrét üzlet/hálózat/termékkör]",
                _validated_text(business_context, field="business_context"),
            )

        unresolved = (
            "[Név]",
            "[település]",
            "[méret]",
            "[hirdetés linkje]",
            "[egyedi leiratkozási link]",
            "[konkrét üzlet/hálózat/termékkör]",
        )
        if recipient_type == "architect_office":
            unresolved += (
                "Tisztelt XY!",
                "(XY, CC, ZZ)",
                "Cégünk, az XY 1989",
            )
        if any(marker in body for marker in unresolved):
            raise GrowthRegistryError("Canonical first-contact render has unresolved markers")
        subject = template.get("subject")
        if recipient_type == "land_owner" and subject is not None:
            subject = _replace_once(
                str(subject),
                "[település]",
                _validated_text(listing_location, field="listing_location"),
            )
            subject = _replace_once(
                str(subject),
                "[méret]",
                _validated_text(listing_size, field="listing_size"),
            )
        blocked_reasons = (
            ("owner_approved_subject_missing_no_fallback",) if subject is None else ()
        )
        body_html = self._body_html(body, template)
        if subject is not None:
            self._assert_brand_isolation(
                sender_brand_id=str(template["sender_brand_id"]),
                subject=str(subject),
                body_text=body,
            )
        return RenderedFirstContact(
            template_id=str(template["template_id"]),
            recipient_type=recipient_type,
            sender_brand_id=str(template["sender_brand_id"]),
            subject=str(subject) if subject is not None else None,
            body_text=body,
            body_html=body_html,
            sendable=not blocked_reasons,
            blocked_reasons=blocked_reasons,
            registry_sha256=self.source_sha256,
            owner_body_sha256=str(template["owner_approved_body_text_sha256_utf8"]),
            render_input=render_input,
        )

    def assert_current_render(
        self,
        *,
        metadata: dict[str, Any],
        subject: str,
        body_text: str,
    ) -> str:
        if metadata.get("registry_sha256") != self.source_sha256:
            raise GrowthRegistryError("canonical_registry_changed_after_queue")
        render_input = metadata.get("render_input")
        if not isinstance(render_input, dict):
            raise GrowthRegistryError("canonical_render_input_missing")
        rendered = self.render(**render_input)
        if not rendered.sendable:
            raise GrowthRegistryError("canonical_template_is_not_sendable")
        if rendered.template_id != metadata.get("template_id"):
            raise GrowthRegistryError("canonical_template_id_changed_after_queue")
        if rendered.sender_brand_id != metadata.get("sender_brand_id"):
            raise GrowthRegistryError("canonical_sender_brand_changed_after_queue")
        if rendered.owner_body_sha256 != metadata.get("owner_body_sha256"):
            raise GrowthRegistryError("canonical_owner_body_changed_after_queue")
        if rendered.subject != subject or rendered.body_text != body_text:
            raise GrowthRegistryError("canonical_rendered_payload_mismatch")
        if _sha256_text(rendered.body_html) != metadata.get(
            "rendered_body_html_sha256"
        ):
            raise GrowthRegistryError("canonical_rendered_html_mismatch")
        return rendered.body_html

    def readiness(self) -> dict[str, Any]:
        return {
            "registry_id": self.raw["registry_id"],
            "registry_version": self.raw["registry_version"],
            "registry_sha256": self.source_sha256,
            "status": self.raw["status"],
            "fallback_policy": self.raw["fallback_policy"],
            "templates": [
                {
                    "template_id": template_id,
                    "recipient_type": str(template["recipient_type"]),
                    "status": template["status"],
                    "subject_status": template["subject_status"],
                    "subject": template["subject"],
                    "subject_immutable": bool(template.get("subject_immutable")),
                    "ai_modification_allowed": template["ai_modification_allowed"],
                    "allowed_replacements": list(template.get("allowed_replacements") or []),
                    "owner_body_sha256": template[
                        "owner_approved_body_text_sha256_utf8"
                    ],
                    "owner_body_utf8_bytes": template[
                        "owner_approved_body_text_utf8_bytes"
                    ],
                }
                for template_id, template in sorted(self.templates_by_id.items())
            ],
            "archived_templates": [
                {
                    "template_id": str(template["template_id"]),
                    "recipient_type": str(template["recipient_type"]),
                    "status": list(template["status"]),
                    "active": bool(template["active"]),
                    "fallback_allowed": bool(template["fallback_allowed"]),
                    "replaced_by": str(template["replaced_by"]),
                }
                for template in self.raw["archived_templates"]
            ],
            "hard_gates": [
                str(gate["gate_id"]) for gate in self.raw.get("hard_gates") or []
            ],
            "ready": True,
        }
