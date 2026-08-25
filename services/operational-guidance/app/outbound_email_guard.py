from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from email.utils import parseaddr


class OutboundEmailBlocked(ValueError):
    pass


@dataclass(frozen=True)
class BrandIdentity:
    name: str
    domains: tuple[str, ...]
    aliases: tuple[str, ...]


BRANDS: dict[str, BrandIdentity] = {
    "imperial-holding": BrandIdentity("Imperial Holding", ("imperialholding.hu",), ("imperial holding",)),
    "imperial-intelligence": BrandIdentity("Imperial Intelligence", ("imperialintelligence.hu",), ("imperial intelligence",)),
    "imperial-construction": BrandIdentity("Imperial Construction", ("imperialconstruction.hu",), ("imperial construction",)),
    "imperial-knowledge": BrandIdentity("Imperial Knowledge", ("imperialknowledge.hu",), ("imperial knowledge",)),
    "imperial-technologies": BrandIdentity("Imperial Technologies", ("imperialtechnologies.hu",), ("imperial technologies",)),
    "imperial-venture-studio": BrandIdentity("Imperial Venture Studio", ("imperialventurestudio.hu",), ("imperial venture studio",)),
    "property360": BrandIdentity("Property360", ("property360.hu",), ("property360", "property 360")),
    "baushield": BrandIdentity("BauShield", ("baushield.hu",), ("baushield", "bau shield")),
    "bautica": BrandIdentity("Bautica", ("bautica.hu",), ("bautica",)),
    "prefab": BrandIdentity("Prefab", ("prefab.hu",), ("prefab",)),
    "exitflow": BrandIdentity("ExitFlow", ("exitflow.hu",), ("exitflow", "exit flow")),
    "veritas": BrandIdentity("Veritas Construct", ("veritasconstruct.hu",), ("veritas construct", "veritas")),
    "baufreund": BrandIdentity("BauFreund", ("baufreund.hu",), ("baufreund", "bau freund")),
    "danish-fabrik": BrandIdentity("Danish Fabrik", ("danishfabrik.hu",), ("danish fabrik",)),
    "timberhaus": BrandIdentity("Timberhaus", ("timberhaus.hu",), ("timberhaus", "timber haus")),
    "casa-moderna": BrandIdentity("Casa Moderna", ("casamoderna.hu",), ("casa moderna",)),
    "everyday-homes": BrandIdentity("Everyday Homes", ("everydayhomes.hu",), ("everyday homes",)),
    "family-homes": BrandIdentity("Family Homes", ("familyhomes.hu",), ("family homes",)),
    "budapesti-magasepito-vallalat": BrandIdentity(
        "Budapesti Magasépítő Vállalat",
        ("budapestimagasepito.hu",),
        ("budapesti magasépítő vállalat", "budapesti magasepito vallalat"),
    ),
    "red-property": BrandIdentity("RED Property", ("redproperty.hu",), ("red property",)),
}

JARGON = (
    "process card", "checklist", "workflow", "pipeline", "handoff", "routing", "route",
    "checkpoint", "run", "ledger", "dashboard", "lifecycle", "funnel", "stakeholder",
    "lead scoring", "lead", "leadgenerátor", "lead generátor", "lead generator",
    "outreach", "pilot", "opt-in", "referral", "landing", "readback", "budget-check",
    "value engineering", "due diligence", "white-label", "oem", "sla", "fit-out",
    "triázs", "partnercsatorna", "munkacsomag", "bom", "dfma", "projectcanary",
    "deduplikáció", "kompetenciaalapú hozzárendelés", "kompetencia alapján rendel",
    "projektjel-feldolgozás", "projektjel feldolgozás", "projektfigyelő rendszer",
    "strukturált együttműködés", "ügyfélvédelmi keretek", "korai fejlesztési jel",
    "auditigény", "audit igény",
    "api", "backend", "frontend", "endpoint", "deployment", "deploy", "sprint",
    "ticket", "task", "scope", "backlog", "milestone", "roadmap", "stack",
    "framework", "interface", "webhook", "payload", "prompt", "rollout", "release",
    "projektmenedzsment", "projektmenedzser", "projekt manager", "projektkontroll",
    "projektirányítás", "integráció", "automatizáció", "orchestration", "orchesztráció",
    "partnerattribúció", "attribúció", "delivery modell", "raw adatbázis", "státusz",
    "eszkaláció",
)

JARGON_PATTERNS = (
    (r"(?<!\w)strukturált(?:\s+[\w-]+){0,2}\s+együttműköd[\w-]*", "strukturált együttműködés"),
    (r"(?<!\w)projektjel[- ]feldolgoz[\w-]*", "projektjel-feldolgozás"),
    (r"(?<!\w)ügyfélvédelmi\s+keret[\w-]*", "ügyfélvédelmi keretek"),
    (r"(?<!\w)kompetencia\s+alapján\s+rendel[\w-]*", "kompetencia alapján rendel"),
    (r"(?<!\w)korai\s+fejlesztési\s+jel[\w-]*", "korai fejlesztési jel"),
    (r"(?<!\w)audit[- ]?igény[\w-]*", "auditigény"),
    (r"(?<!\w)deduplik[\w-]*", "deduplikáció"),
    (r"(?<!\w)partnercsatorn[\w-]*", "partnercsatorna"),
    (r"(?<!\w)munkacsomag[\w-]*", "munkacsomag"),
    (r"(?<!\w)lead(?:ek|et|eket|nek|del|ből|re|lista|listát|generátor|generátort|generátorral)?(?!\w)", "lead"),
    (r"(?<!\w)(?:pilot|outreach|routing|pipeline|triázs|projectcanary)[\w-]*", "külső szakzsargon"),
)

PURPOSE = ("azért írunk", "szeretnénk", "keressük", "kérjük")
BENEFIT = ("ez segít", "tudunk segíteni", "jutalék", "megbízási lehetőség", "kapacitást")
NEXT_STEP = ("kérjük", "válaszoljon", "válaszoljanak", "írjon", "írják", "nézze át")
SUFFIX = r"(?:t|ot|et|öt|at|k|ok|ek|ök|ak|okat|eket|öket|akat|nak|nek|ban|ben|ba|be|ból|ből|hoz|hez|höz|ról|ről|tól|től|ra|re|ért|ig|ként|on|en|ön|n|nál|nél|ja|je|juk|jük|os|es|ös|i|val|vel|[bcdfghjklmnpqrstvwxyz](?:al|el))"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _contains(text: str, phrase: str) -> bool:
    escaped = re.escape(_normalize(phrase))
    return bool(re.search(rf"(?<!\w){escaped}(?:{SUFFIX})?(?!\w)", text))


def _domain(sender_email: str) -> str:
    address = parseaddr(sender_email)[1].casefold()
    if address.count("@") != 1:
        raise OutboundEmailBlocked("sender_email_invalid")
    domain = address.rsplit("@", 1)[1].rstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]+", domain) or ".." in domain:
        raise OutboundEmailBlocked("sender_email_invalid")
    return domain


def brand_from_sender(sender_email: str) -> tuple[str, BrandIdentity]:
    domain = _domain(sender_email)
    for brand_id, identity in BRANDS.items():
        if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in identity.domains):
            display_name = _normalize(parseaddr(sender_email)[0])
            allowed_display_names = {_normalize(alias) for alias in identity.aliases}
            if display_name and display_name not in allowed_display_names:
                raise OutboundEmailBlocked("sender_brand_mismatch")
            return brand_id, identity
    raise OutboundEmailBlocked("sender_brand_unknown")


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\wÁÉÍÓÖŐÚÜŰáéíóöőúüű-]+\b", value, re.UNICODE))


def require_plain_single_brand_email(*, sender_email: str, subject: str, body: str) -> str:
    expected_id, expected = brand_from_sender(sender_email)
    normalized = _normalize(f"{subject}\n{body}")
    normalized_body = _normalize(body)
    errors: list[str] = []

    if not subject.strip():
        errors.append("subject_missing")
    if not body.strip():
        errors.append("body_missing")
    if _word_count(subject) > 8:
        errors.append("subject_over_8_words")
    if _word_count(body) > 180:
        errors.append("body_over_180_words")
    sentences = [part for part in re.split(r"[.!?]+(?:\s+|$)|\n\s*\n+", body) if part.strip()]
    if any(_word_count(sentence) > 25 for sentence in sentences):
        errors.append("sentence_over_25_words")

    found_jargon = {term for term in JARGON if _contains(normalized, term)}
    found_jargon.update(
        label for pattern, label in JARGON_PATTERNS if re.search(pattern, normalized)
    )
    found_jargon = sorted(found_jargon)
    if found_jargon:
        errors.append("jargon:" + "|".join(found_jargon))

    detected: set[str] = set()
    for brand_id, identity in BRANDS.items():
        if any(_contains(normalized, alias) for alias in identity.aliases):
            detected.add(brand_id)
        if any(re.search(rf"(?<![a-z0-9.-])(?:[a-z0-9-]+\.)*{re.escape(domain)}(?![a-z0-9.-])", normalized) for domain in identity.domains):
            detected.add(brand_id)
    if expected_id not in detected:
        errors.append("expected_brand_missing")
    foreign = sorted(detected - {expected_id})
    if foreign:
        errors.append("foreign_brand:" + "|".join(foreign))

    if not any(_contains(normalized_body, marker) for marker in PURPOSE):
        errors.append("purpose_not_clear")
    if not any(_contains(normalized_body, marker) for marker in BENEFIT):
        errors.append("recipient_benefit_not_clear")
    action_sentences = sum(
        1 for sentence in sentences if any(_contains(_normalize(sentence), marker) for marker in NEXT_STEP)
    )
    if action_sentences == 0:
        errors.append("next_step_not_clear")
    elif action_sentences > 1:
        errors.append("multiple_next_steps")

    if errors:
        raise OutboundEmailBlocked("OUTBOUND_COPY_BLOCKED:" + ",".join(dict.fromkeys(errors)))
    return expected.name
