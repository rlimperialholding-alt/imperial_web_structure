from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from typing import Any
from urllib.parse import urlparse

POLICY_VERSION = "2026-08-25"

OWNER_HARD_SUPPRESSION = "HARD_SUPPRESSED_OWNER_DIRECTIVE_2026-08-25"
PUBLIC_AUTHORITY_HARD_SUPPRESSION = (
    "HARD_SUPPRESSED_PUBLIC_PROCUREMENT_AUTHORITY_2026-08-25"
)
SUPPRESSION_REVIEW = "SUPPRESSION_REVIEW"
ALLOWED = "ALLOWED"

_TURCZER_EMAILS = {"turczer.jozsef@gmail.com"}
_GDN_DOMAINS = {"gdn-ingatlan.hu"}
_OC_BLOCKED_LOCAL_PARTS = {
    "tdg",
    "2ker.bemrakpart",
    "2ker.uromiutca",
    "2ker.lajosutca",
    "hidegkut",
    "mompark",
    "varosmajor",
}
_OC_BLOCKED_OFFICE_SLUGS = {
    "ii kerulet tdg",
    "ii kerulet bem rakpart",
    "ii kerulet uromi utca",
    "ii kerulet lajos utca",
    "ii a kerulet hidegkuti ut",
    "xii kerulet mom park",
    "xii kerulet varosmajor utca",
}
_OC_BLOCKED_OFFICE_NAMES = {
    "bem rakpart",
    "uromi utca",
    "lajos utca",
    "hidegkuti ut",
    "mom park",
    "varosmajor utca",
}
_PUBLIC_ORGANIZATION_CLASSES = {
    "contracting authority",
    "government",
    "government agency",
    "government office",
    "higher education",
    "ministry",
    "municipal institution",
    "municipality",
    "public authority",
    "public contracting authority",
    "public institution",
    "public procurement contracting authority",
    "state body",
    "state hospital",
    "state institution",
    "university",
}
_PUBLIC_NAME_PHRASES = {
    "allamkincstar",
    "allami korhaz",
    "allami intezmeny",
    "egyetem",
    "foiskola",
    "hatosag",
    "katasztrofavedelmi igazgatosag",
    "kormanyhivatal",
    "magyar allam",
    "magyar honvedseg",
    "miniszterium",
    "nemzeti ado es vamhivatal",
    "onkormanyzat",
    "polgarmesteri hivatal",
    "rendor fokapitanysag",
    "rendor kapitanysag",
    "szakkepzesi centrum",
    "tankeruleti kozpont",
}
_OUTREACH_PURPOSES = {
    "capacity",
    "cold email",
    "growth outreach",
    "followup",
    "outreach",
    "partner",
    "procurement",
    "sales",
    "supplier",
    "tender invitation",
}
_PUBLIC_ENTITY_SUFFIXES = {
    "",
    "a",
    "at",
    "ban",
    "be",
    "ben",
    "ba",
    "bol",
    "e",
    "en",
    "ert",
    "et",
    "hez",
    "hoz",
    "i",
    "ja",
    "je",
    "nak",
    "nek",
    "on",
    "ot",
    "ra",
    "re",
    "rol",
    "t",
    "tol",
    "val",
    "vel",
}
_OC_BLOCKED_DISTRICT_PATTERN = re.compile(
    r"(?:^| )(?:budapest )?(?:ii(?: a)?|2(?: a)?|xii|12) "
    r"(?:ker|kerulet|keruleti)(?: |$)"
)


def _normalized(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def _email_domain(email: str) -> str:
    value = (email or "").strip().casefold()
    return value.rsplit("@", 1)[1].rstrip(".") if value.count("@") == 1 else ""


def _host(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").casefold().rstrip(".")


def _domain_matches(domain: str, candidates: set[str]) -> bool:
    return any(domain == candidate or domain.endswith(f".{candidate}") for candidate in candidates)


def _contains_phrase(value: str, phrase: str) -> bool:
    return bool(re.search(rf"(?:^| ){re.escape(phrase)}(?: |$)", value))


def _contains_public_name_phrase(value: str, phrase: str) -> bool:
    words = value.split()
    phrase_words = phrase.split()
    width = len(phrase_words)
    for index in range(len(words) - width + 1):
        candidate = words[index : index + width]
        if candidate[:-1] != phrase_words[:-1]:
            continue
        last_word = candidate[-1]
        base_word = phrase_words[-1]
        if last_word == base_word or (
            last_word.startswith(base_word)
            and last_word[len(base_word) :] in _PUBLIC_ENTITY_SUFFIXES
        ):
            return True
    return False


@dataclass(frozen=True)
class RecipientPolicyContext:
    email: str = ""
    company_name: str = ""
    contact_name: str = ""
    location: str = ""
    public_contact_url: str = ""
    evidence_url: str = ""
    website_url: str = ""
    organization_class: str = ""
    contracting_authority_verified: bool = False
    contracting_authority_suspected: bool = False
    organization_affiliations: tuple[str, ...] = ()
    office_affiliations: tuple[str, ...] = ()
    purpose: str = "outreach"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["organization_affiliations"] = list(self.organization_affiliations)
        value["office_affiliations"] = list(self.office_affiliations)
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None, **overrides: Any):
        source = dict(value or {})
        source.update({key: item for key, item in overrides.items() if item is not None})
        allowed = {field.name for field in fields(cls)}
        source = {key: item for key, item in source.items() if key in allowed}
        for key in ("organization_affiliations", "office_affiliations"):
            item = source.get(key, ())
            if isinstance(item, str):
                item = (item,)
            elif not isinstance(item, (list, tuple, set)):
                item = ()
            source[key] = tuple(str(entry) for entry in item if str(entry).strip())
        return cls(**source)


@dataclass(frozen=True)
class RecipientGateDecision:
    allowed: bool
    status: str
    reason: str
    matches: tuple[str, ...] = ()


class OutboundRecipientBlocked(ValueError):
    def __init__(self, decision: RecipientGateDecision):
        super().__init__(f"{decision.status}: {decision.reason}")
        self.decision = decision


def _all_identity_text(context: RecipientPolicyContext) -> str:
    return _normalized(
        " ".join(
            (
                context.company_name,
                context.contact_name,
                *context.organization_affiliations,
                *context.office_affiliations,
            )
        )
    )


def _organization_identity_text(context: RecipientPolicyContext) -> str:
    return _normalized(
        " ".join(
            (
                context.company_name,
                *context.organization_affiliations,
                *context.office_affiliations,
            )
        )
    )


def _turczer_match(context: RecipientPolicyContext, identity: str) -> tuple[str, ...]:
    matches: list[str] = []
    if context.email.strip().casefold() in _TURCZER_EMAILS:
        matches.append("turczer_verified_email")
    if _contains_phrase(identity, "turczer") and _contains_phrase(identity, "jozsef"):
        matches.append("turczer_jozsef_name")
    return tuple(matches)


def _gdn_match(context: RecipientPolicyContext, identity: str) -> tuple[str, ...]:
    matches: list[str] = []
    domains = {
        _email_domain(context.email),
        _host(context.public_contact_url),
        _host(context.website_url),
    }
    if any(_domain_matches(domain, _GDN_DOMAINS) for domain in domains if domain):
        matches.append("gdn_network_domain")
    if _contains_phrase(identity, "gdn"):
        matches.append("gdn_network_affiliation")
    return tuple(matches)


def _oc_decision(
    context: RecipientPolicyContext, identity: str
) -> RecipientGateDecision | None:
    email = context.email.strip().casefold()
    domain = _email_domain(email)
    local_part = email.split("@", 1)[0] if domain else ""
    url_hosts = {
        _host(context.public_contact_url),
        _host(context.website_url),
    }
    is_oc = (
        domain == "oc.hu"
        or any(host == "oc.hu" or host.endswith(".oc.hu") for host in url_hosts if host)
        or _contains_phrase(identity, "otthon centrum")
    )
    if not is_oc:
        return None

    office_hard_match = (
        local_part in _OC_BLOCKED_LOCAL_PARTS
        or any(_contains_phrase(identity, slug) for slug in _OC_BLOCKED_OFFICE_SLUGS)
        or any(_contains_phrase(identity, name) for name in _OC_BLOCKED_OFFICE_NAMES)
        or bool(_OC_BLOCKED_DISTRICT_PATTERN.search(identity))
    )
    if office_hard_match:
        return RecipientGateDecision(
            allowed=False,
            status=OWNER_HARD_SUPPRESSION,
            reason="Az Otthon Centrum Budapest II/II-A/XII. kerületi irodái tiltólistán vannak.",
            matches=("oc_budapest_ii_iia_xii_office",),
        )
    if domain == "oc.hu":
        return RecipientGateDecision(
            allowed=False,
            status=SUPPRESSION_REVIEW,
            reason=(
                "Az @oc.hu cím irodai kapcsolata nem igazolt; emberi ellenőrzésig nem küldhető."
            ),
            matches=("unresolved_oc_hu_affiliation",),
        )
    return None


def _public_authority_match(context: RecipientPolicyContext, identity: str) -> tuple[str, ...]:
    matches: list[str] = []
    organization_class = _normalized(context.organization_class).replace("_", " ")
    if context.contracting_authority_verified:
        matches.append("verified_contracting_authority")
    if organization_class in _PUBLIC_ORGANIZATION_CLASSES:
        matches.append("public_organization_class")
    if any(_contains_public_name_phrase(identity, phrase) for phrase in _PUBLIC_NAME_PHRASES):
        matches.append("public_authority_name")
    domains = {
        _email_domain(context.email),
        _host(context.public_contact_url),
        _host(context.website_url),
    }
    if any(
        domain == "kormany.hu"
        or domain.endswith(".kormany.hu")
        or domain == "gov.hu"
        or domain.endswith(".gov.hu")
        for domain in domains
        if domain
    ):
        matches.append("government_domain")
    return tuple(sorted(set(matches)))


def evaluate_outbound_recipient(context: RecipientPolicyContext) -> RecipientGateDecision:
    identity = _all_identity_text(context)
    organization_identity = _organization_identity_text(context)
    owner_matches = _turczer_match(context, identity) + _gdn_match(context, identity)
    if owner_matches:
        return RecipientGateDecision(
            allowed=False,
            status=OWNER_HARD_SUPPRESSION,
            reason="A címzett tulajdonosi utasítás alapján nem kereshető meg.",
            matches=tuple(sorted(set(owner_matches))),
        )

    oc_decision = _oc_decision(context, identity)
    if oc_decision:
        return oc_decision

    purpose = _normalized(context.purpose)
    public_matches = _public_authority_match(context, organization_identity)
    if purpose in _OUTREACH_PURPOSES and public_matches:
        return RecipientGateDecision(
            allowed=False,
            status=PUBLIC_AUTHORITY_HARD_SUPPRESSION,
            reason=(
                "Közbeszerzés-köteles ajánlatkérőnek értékesítési, partneri vagy "
                "beszállítói megkeresés nem küldhető."
            ),
            matches=public_matches,
        )
    if purpose in _OUTREACH_PURPOSES and context.contracting_authority_suspected:
        return RecipientGateDecision(
            allowed=False,
            status=SUPPRESSION_REVIEW,
            reason="A címzett ajánlatkérői státusza nem tisztázott; ellenőrzésig nem küldhető.",
            matches=("suspected_contracting_authority",),
        )
    return RecipientGateDecision(
        allowed=True,
        status=ALLOWED,
        reason="A központi címzettkapu nem talált tiltó okot.",
    )


def require_outbound_recipient(context: RecipientPolicyContext) -> RecipientGateDecision:
    decision = evaluate_outbound_recipient(context)
    if not decision.allowed:
        raise OutboundRecipientBlocked(decision)
    return decision
