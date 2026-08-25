from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from email.utils import parseaddr


@dataclass(frozen=True)
class OutboundCopyCheck:
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


class OutboundCopyViolation(ValueError):
    def __init__(self, errors: tuple[str, ...]) -> None:
        self.errors = errors
        super().__init__("Kimenő levél blokkolva: " + ", ".join(errors))


BRAND_ALIASES: dict[str, tuple[str, ...]] = {
    "imperial-holding": ("imperial holding",),
    "imperial-intelligence": ("imperial intelligence",),
    "imperial-construction": ("imperial construction",),
    "imperial-knowledge": ("imperial knowledge",),
    "imperial-technologies": ("imperial technologies",),
    "imperial-venture-studio": ("imperial venture studio",),
    "property360": ("property360", "property 360"),
    "baushield": ("baushield", "bau shield"),
    "bautica": ("bautica",),
    "prefab": ("prefab",),
    "exitflow": ("exitflow", "exit flow"),
    "veritas": ("veritas construct", "veritas"),
    "baufreund": ("baufreund", "bau freund"),
    "danish-fabrik": ("danish fabrik",),
    "timberhaus": ("timberhaus", "timber haus"),
    "casa-moderna": ("casa moderna", "casa moderna living"),
    "everyday-homes": ("everyday homes", "everyday homes stories"),
    "family-homes": ("family homes", "family homes családi magazin"),
    "budapesti-magasepito-vallalat": (
        "budapesti magasépítő vállalat",
        "budapesti magasepito vallalat",
    ),
    "red-property": ("red property", "red property report"),
}

BRAND_ID_ALIASES = {
    "imperial": "imperial-holding",
    "imperial_holding": "imperial-holding",
    "imperialholding": "imperial-holding",
    "veritas-construct": "veritas",
    "veritas_construct": "veritas",
    "danishfabrik": "danish-fabrik",
    "casamoderna": "casa-moderna",
    "everydayhomes": "everyday-homes",
    "familyhomes": "family-homes",
    "budapestimagasepito": "budapesti-magasepito-vallalat",
    "budapesti-magasepito": "budapesti-magasepito-vallalat",
    "redproperty": "red-property",
    "property-360": "property360",
}

BRAND_SENDER_DOMAINS: dict[str, tuple[str, ...]] = {
    "imperial-holding": ("imperialholding.hu", "myimperial.hu"),
    "imperial-intelligence": ("imperialintelligence.hu",),
    "imperial-construction": ("imperialconstruction.hu",),
    "imperial-knowledge": ("imperialknowledge.hu",),
    "imperial-technologies": ("imperialtechnologies.hu",),
    "imperial-venture-studio": ("imperialventurestudio.hu",),
    "property360": ("property360.hu",),
    "baushield": ("baushield.hu",),
    "bautica": ("bautica.hu", "bautica.test"),
    "prefab": ("prefab.hu",),
    "exitflow": ("exitflow.hu",),
    "veritas": ("veritasconstruct.hu",),
    "baufreund": ("baufreund.hu",),
    "danish-fabrik": ("danishfabrik.hu",),
    "timberhaus": ("timberhaus.hu",),
    "casa-moderna": ("casamoderna.hu",),
    "everyday-homes": ("everydayhomes.hu",),
    "family-homes": ("familyhomes.hu",),
    "budapesti-magasepito-vallalat": ("budapestimagasepito.hu",),
    "red-property": ("redproperty.hu",),
}

JARGON = (
    "workflow",
    "pipeline",
    "handoff",
    "routing",
    "route",
    "checkpoint",
    "run",
    "ledger",
    "dashboard",
    "lifecycle",
    "funnel",
    "stakeholder",
    "lead scoring",
    "lead",
    "leadgenerátor",
    "lead generátor",
    "lead generator",
    "outreach",
    "pilot",
    "opt-in",
    "referral",
    "landing",
    "readback",
    "budget-check",
    "value engineering",
    "due diligence",
    "white-label",
    "oem",
    "sla",
    "fit-out",
    "triázs",
    "partnercsatorna",
    "munkacsomag",
    "bom",
    "dfma",
    "projectcanary",
    "deduplikáció",
    "kompetenciaalapú hozzárendelés",
    "kompetencia alapján rendel",
    "projektjel-feldolgozás",
    "projektjel feldolgozás",
    "strukturált együttműködés",
    "ügyfélvédelmi keretek",
    "korai fejlesztési jel",
    "auditigény",
    "eszkaláció",
    "api",
    "backend",
    "frontend",
    "endpoint",
    "deployment",
    "deploy",
    "sprint",
    "ticket",
    "task",
    "scope",
    "backlog",
    "milestone",
    "roadmap",
    "stack",
    "framework",
    "interface",
    "webhook",
    "payload",
    "prompt",
    "rollout",
    "release",
    "checklist",
    "projektmenedzsment",
    "projektmenedzser",
    "projekt manager",
    "projektkontroll",
    "projektirányítás",
    "projektfigyelő rendszer",
    "integráció",
    "automatizáció",
    "orchestration",
    "orchesztráció",
    "partnerattribúció",
    "attribúció",
    "delivery modell",
    "raw adatbázis",
    "státusz",
)

JARGON_PATTERNS = (
    (
        r"(?<!\w)strukturált(?:\s+[\w-]+){0,2}\s+együttműköd[\w-]*",
        "strukturált együttműködés",
    ),
    (r"(?<!\w)projektjel[- ]feldolgoz[\w-]*", "projektjel-feldolgozás"),
    (r"(?<!\w)ügyfélvédelmi\s+keret[\w-]*", "ügyfélvédelmi keretek"),
    (r"(?<!\w)kompetencia\s+alapján\s+rendel[\w-]*", "kompetencia alapján rendel"),
    (r"(?<!\w)korai\s+fejlesztési\s+jel[\w-]*", "korai fejlesztési jel"),
    (r"(?<!\w)auditigény[\w-]*", "auditigény"),
    (r"(?<!\w)deduplik[\w-]*", "deduplikáció"),
    (
        r"(?<!\w)lead(?:ek|et|eket|nek|del|ből|re|lista|listát|generátor|generátort|"
        r"generátorral)?(?!\w)",
        "lead",
    ),
    (
        r"(?<!\w)(?:pilot|outreach|routing|pipeline|triázs|partnercsatorna|"
        r"munkacsomag)[\w-]*",
        "külső szakzsargon",
    ),
)

HUNGARIAN_SUFFIX_PATTERN = (
    r"(?:t|ot|et|öt|at|k|ok|ek|ök|ak|okat|eket|öket|akat|nak|nek|ban|ben|ba|be|ból|ből|"
    r"hoz|hez|höz|ról|ről|tól|től|ra|re|ért|ig|ként|on|en|ön|n|nál|"
    r"nél|ja|je|juk|jük|os|es|ös|i|val|vel|[bcdfghjklmnpqrstvwxyz](?:al|el))"
)

PURPOSE_MARKERS = (
    "szeretnénk",
    "keressük",
    "keresünk",
    "felajánljuk",
    "fel tudunk ajánlani",
    "kínálunk",
    "segítünk",
    "meghívjuk",
    "azért keressük",
    "azért írunk",
    "visszatérünk",
)

BENEFIT_MARKERS = (
    "tudunk segíteni",
    "segítünk önnek",
    "segítünk önöknek",
    "ez segít önnek",
    "ez segít önöknek",
    "jutalék",
    "megbízási lehetőség",
    "új megbízás",
    "kapacitást tudunk adni",
    "kapacitásunkat felajánljuk",
    "kapacitásunkat szeretnénk felajánlani",
    "fel tudunk ajánlani",
    "előnyt jelent",
    "előnyös önnek",
    "előnyös önöknek",
    "időt takarít meg",
    "költséget takarít meg",
)

NEXT_STEP_MARKERS = (
    "kérjük",
    "válaszoljon",
    "válaszoljanak",
    "írjon",
    "írják",
    "egyeztessünk",
    "egyeztethetünk",
    "időpont",
    "hívjon",
    "küldje",
    "küldjék",
    "adja meg",
    "adják meg",
    "nyissa meg",
    "fogadja el",
)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", value).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(_normalize(phrase))}(?!\w)", text))


def _inflected_phrase_variants(phrase: str) -> tuple[str, ...]:
    normalized = _normalize(phrase)
    variants = [normalized]
    if normalized.endswith("a"):
        variants.append(normalized[:-1] + "á")
    elif normalized.endswith("e"):
        variants.append(normalized[:-1] + "é")
    return tuple(dict.fromkeys(variants))


def _contains_inflected_phrase(text: str, phrase: str) -> bool:
    variants = "|".join(re.escape(value) for value in _inflected_phrase_variants(phrase))
    return bool(
        re.search(
            rf"(?<!\w)(?:{variants})(?:-?{HUNGARIAN_SUFFIX_PATTERN})?(?!\w)",
            text,
        )
    )


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\wÀ-ž]+\b", value, flags=re.UNICODE))


def _sentence_lengths(value: str) -> list[int]:
    without_urls = re.sub(r"https?://\S+", "", value)
    return [
        _word_count(part)
        for part in re.split(r"[.!?]+(?:\s+|$)|\n\s*\n+", without_urls)
        if part.strip()
    ]


def _next_step_segment_count(value: str) -> int:
    without_urls = re.sub(r"https?://\S+", "", value)
    segments = [
        segment
        for segment in re.split(r"[.!?]+(?:\s+|$)|\n\s*\n+", without_urls)
        if segment
    ]
    count = 0
    for segment in segments:
        normalized = _normalize(segment)
        if normalized.startswith("leiratkoz") or "ha nem kíván" in normalized:
            continue
        if any(_contains_phrase(normalized, marker) for marker in NEXT_STEP_MARKERS):
            count += 1
    return count


def _canonical_brand(brand_id: str) -> str:
    value = _normalize(brand_id).replace(" ", "-")
    return BRAND_ID_ALIASES.get(value, value)


def _sender_identity(sender_email: str) -> tuple[str, str]:
    display_name, parsed = parseaddr(sender_email)
    if parsed.count("@") != 1:
        raise OutboundCopyViolation(("sender_email_invalid",))
    local, domain = parsed.rsplit("@", 1)
    if not local or not domain:
        raise OutboundCopyViolation(("sender_email_invalid",))
    try:
        normalized = domain.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise OutboundCopyViolation(("sender_email_invalid",)) from exc
    if not normalized or ".." in normalized:
        raise OutboundCopyViolation(("sender_email_invalid",))
    return display_name.strip(), normalized


def _domain_is_or_is_below(domain: str, allowed_domain: str) -> bool:
    return domain == allowed_domain or domain.endswith(f".{allowed_domain}")


def brand_id_from_sender(sender_email: str, *, default: str | None = None) -> str:
    display_name, domain = _sender_identity(sender_email)
    for brand_id, allowed_domains in BRAND_SENDER_DOMAINS.items():
        if any(_domain_is_or_is_below(domain, allowed) for allowed in allowed_domains):
            allowed_display_names = {
                _normalize(alias) for alias in BRAND_ALIASES.get(brand_id, ())
            }
            if display_name and _normalize(display_name) not in allowed_display_names:
                raise OutboundCopyViolation(("sender_brand_mismatch",))
            return brand_id
    if default:
        expected_brand = _canonical_brand(default)
        allowed_domains = BRAND_SENDER_DOMAINS.get(expected_brand, ())
        if any(_domain_is_or_is_below(domain, allowed) for allowed in allowed_domains):
            return expected_brand
    raise OutboundCopyViolation(("sender_brand_unknown",))


def require_sender_brand(sender_email: str, brand_id: str) -> None:
    expected_brand = _canonical_brand(brand_id)
    actual_brand = brand_id_from_sender(sender_email)
    if actual_brand != expected_brand:
        raise OutboundCopyViolation(("sender_brand_mismatch",))


def _detected_link_brands(value: str) -> set[str]:
    found: set[str] = set()
    normalized = value.casefold()
    for brand_id, allowed_domains in BRAND_SENDER_DOMAINS.items():
        for allowed_domain in allowed_domains:
            pattern = (
                rf"(?<![a-z0-9.-])(?:[a-z0-9-]+\.)*"
                rf"{re.escape(allowed_domain)}(?![a-z0-9-]|\.[a-z0-9-])"
            )
            if re.search(pattern, normalized):
                found.add(brand_id)
                break
    return found


def _detected_brands(text: str) -> set[str]:
    normalized = _normalize(text)
    found: set[str] = set()
    for brand_id, aliases in BRAND_ALIASES.items():
        if any(_contains_inflected_phrase(normalized, alias) for alias in aliases):
            found.add(brand_id)
    return found


def check_outbound_email(
    *,
    subject: str,
    body: str,
    brand_id: str,
    kind: str = "outreach",
    max_body_words: int | None = None,
) -> OutboundCopyCheck:
    """Deterministic, fail-closed gate for automatically prepared e-mail copy.

    Every automatic message requires an explicit purpose, recipient benefit and
    one clear next step. ``kind`` only selects the applicable word limit.
    """

    subject = (subject or "").strip()
    body = (body or "").strip()
    normalized = _normalize(f"{subject}\n{body}")
    normalized_body = _normalize(body)
    errors: list[str] = []

    if not subject:
        errors.append("subject_missing")
    if not body:
        errors.append("body_missing")
    if _word_count(subject) > 8:
        errors.append("subject_over_8_words")

    limit = max_body_words if max_body_words is not None else {
        "outreach": 120,
        "followup": 80,
        "internal": 180,
        "transactional": 180,
    }.get(kind, 120)
    if _word_count(body) > limit:
        errors.append(f"body_over_{limit}_words")
    if any(length > 25 for length in _sentence_lengths(body)):
        errors.append("sentence_over_25_words")

    jargon = {phrase for phrase in JARGON if _contains_inflected_phrase(normalized, phrase)}
    jargon.update(
        label for pattern, label in JARGON_PATTERNS if re.search(pattern, normalized)
    )
    if jargon:
        errors.append("jargon:" + "|".join(sorted(jargon)))

    expected_brand = _canonical_brand(brand_id)
    detected_brands = _detected_brands(normalized) | _detected_link_brands(
        f"{subject}\n{body}"
    )
    if expected_brand not in detected_brands:
        errors.append("expected_brand_missing")
    foreign_brands = sorted(detected_brands - {expected_brand})
    if foreign_brands:
        errors.append("foreign_brand:" + "|".join(foreign_brands))

    if not any(_contains_phrase(normalized_body, marker) for marker in PURPOSE_MARKERS):
        errors.append("purpose_not_clear")
    if not any(
        _contains_inflected_phrase(normalized_body, marker)
        for marker in BENEFIT_MARKERS
    ):
        errors.append("recipient_benefit_not_clear")
    next_step_count = _next_step_segment_count(body)
    if next_step_count == 0:
        errors.append("next_step_not_clear")
    elif next_step_count > 1:
        errors.append("multiple_next_steps")

    return OutboundCopyCheck(tuple(dict.fromkeys(errors)))


def require_outbound_email(**kwargs: object) -> None:
    check = check_outbound_email(**kwargs)  # type: ignore[arg-type]
    if not check.passed:
        raise OutboundCopyViolation(check.errors)
