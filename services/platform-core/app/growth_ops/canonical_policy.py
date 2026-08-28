from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

SPEC_VERSION = "2026-08-20-canonical-wide-v1"
SOURCE_LEDGER_SPREADSHEET_ID = "1ddn6e2EbuafPc_S9_eb6oetBQsp4iOO9cFuMD6sQ4H4"
SOURCE_LEDGER_SHEET_ID = 959591161
SOURCE_LEDGER_SHEET_NAME = "Útvonal-nyilvántartás"
SOURCE_LEDGER_ROUTE_COUNT = 25_494

DAILY_UNIQUE_LEAD_MINIMUM = 100
DAILY_QUESTION_TOPIC_MINIMUM = 80
DAILY_ROUTE_ATTEMPT_MINIMUM = 800
DAILY_CONTENT_BRAND_MINIMUM = 19

IORA_EXECUTIVE_NAME = "Právicz Anna"
IORA_EXECUTIVE_EMAIL = "ugyvezeto@imperialholding.hu"
IORA_INTERNAL_SENDER = "info@imperialholding.hu"

# Owner-provided, customer-facing anchor. It is deliberately not an LLM prompt.
PARTNER_OUTREACH_ANCHOR = (
    "Szeretnénk felajánlani szakmai segítségünket és kapacitásunkat a projekthez, "
    "ha szükség van ránk."
)
PARTNER_OUTREACH_ANCHOR_SHA256 = "7004cccbda5c2e45109edf92474791a4b2fd268d8ffe2de08d093c32f1b1e24f"

# Owner-approved land-listing copy, revised 2026-08-25. These subjects and
# anchors prevent a runtime template or later refactor from changing the
# product, commission, or property-owner offer without an explicit policy
# update.
LAND_OWNER_SUBJECT = (
    "Ingyen elkészítjük a {listing_location}, {listing_size}-es telek + típusház "
    "hirdetését"
)
LAND_OWNER_SUBJECT_SHA256 = (
    "56f96d8def49c6b2c819ab8f1186056b2199b44bc2e40d1d0b0de8ef55af64a6"
)
LAND_AGENT_SUBJECT = "ház eladásában kérnék segítséget"
LAND_AGENT_SUBJECT_SHA256 = (
    "4f5460a60567e226c1fb4c4e4a28b59315738a2eda21ce37eebdbf6d28b43334"
)
LAND_CATALOG_URL = "https://imperialholding.hu/termek/telek-kereso"
LAND_OUTREACH_SERVICE_ANCHOR = (
    "előregyártott készházak és típusházak építésével foglalkozik"
)
LAND_OUTREACH_SERVICE_ANCHOR_SHA256 = (
    "49b13d78545af86f7cce867c44567cf7575085228b7cc81415e16208683d39f3"
)
LAND_AGENT_COMMISSION_ANCHOR = (
    "2,5% jutalékot fizetünk azoknak az ingatlanos partnereinknek, akik a hirdetett "
    "telkeik mellé valamelyik típusházunkat is eladják."
)
LAND_AGENT_COMMISSION_ANCHOR_SHA256 = (
    "ae48724a42c7de14cb30a6715ce488f314320c12b566ac4255ba8bf6ac1bb393"
)
LAND_OWNER_FREE_AD_ANCHOR = (
    "Ingyen, jutalék nélkül meghirdetjük az ingatlanát a telekhez illő "
    "típusházunkkal."
)
LAND_OWNER_FREE_AD_ANCHOR_SHA256 = (
    "09bff47f226817749a551e2cb8d7d44a9481e02d57829a6e47f09b191b1f380c"
)
LAND_OWNER_SERVICE_ANCHOR = (
    "Az Imperial Holding típustervek kulcsrakész építésével foglalkozik."
)
LAND_OWNER_SERVICE_ANCHOR_SHA256 = (
    "0220cfa5398c899f068acdf1530b7002ca00fcc422a2f6895c52883bbe02ee26"
)
LAND_OWNER_PERMISSION_ANCHOR = (
    "Csak az írásos engedélyét kérjük ahhoz, hogy a telket a telek + típusház "
    "ajánlat részeként meghirdethessük. A hirdetési anyagot mi készítjük el."
)
LAND_OWNER_PERMISSION_ANCHOR_SHA256 = (
    "ac08b4c0b92375caecef5ff1d60ccbab18f6a1cadde9ec52a70d578e54147e2f"
)
LAND_OWNER_REPLY_ANCHOR = (
    "A hirdetés engedélyezéséhez válaszoljon emailben: „Engedélyezem a telek "
    "hirdetését.”"
)
LAND_OWNER_REPLY_ANCHOR_SHA256 = (
    "f7094b5d09403e660687a7d7d9abbb771966affde32ca696d4b2f7ca265e452c"
)

ACTIVE_CONTENT_BRANDS = (
    "Imperial",
    "Bautica",
    "Prefab",
    "Casa Moderna",
    "BauFreund",
    "Danish Fabrik",
    "TimberHaus",
    "RED Property",
    "Property360",
    "Everyday Homes",
    "Venture Studio",
    "Family Homes",
    "Imperial Construction",
    "Imperial Intelligence",
    "Imperial Technologies",
    "Imperial Knowledge",
    "ExitFlow",
    "Veritas Construct",
    "BauShield",
)

# Owner-confirmed delivery scope for the initial production phase. Facebook and
# CMS are independent routes, but every public delivery requires an approved image.
# The historical constant name is retained because external checks import it.
FACEBOOK_TEXT_ONLY_TARGETS = {
    "Imperial": ("imperial",),
    "Bautica": ("bautica",),
    "Prefab": ("prefab",),
    "Casa Moderna": ("casa-moderna",),
    "BauFreund": ("baufreund",),
    "Danish Fabrik": ("danish-fabrik",),
    "TimberHaus": ("timberhaus",),
    "RED Property": ("red-property",),
    "Property360": ("property-360",),
    "Everyday Homes": ("everyday-homes",),
    "Family Homes": ("family-homes",),
    "Imperial Construction": ("budapesti-magasepito-vallalat",),
}

CMS_LIVE_TARGETS = {
    "Bautica": "bautica",
    "Prefab": "prefab",
    "BauFreund": "baufreund",
    "Danish Fabrik": "danish-fabrik",
    "TimberHaus": "timberhaus",
}

CONTENT_IMAGE_OWNER = "Imperial Content Image Factory"

BRAND_CONTENT_FOCUS = {
    "Imperial": ("építkezés", "kivitelezés", "ingatlan", "projekt", "műszaki"),
    "Bautica": ("felújítás", "kivitelezés", "építkezés", "bővítés", "otthon"),
    "Prefab": ("előregyártás", "csarnok", "panel", "szerkezet", "kivitelezés"),
    "Casa Moderna": ("prémium otthon", "okosotthon", "komfort", "építészet", "ház"),
    "BauFreund": ("építkezés", "kivitelezés", "ház", "költség", "műszaki"),
    "Danish Fabrik": ("készház", "faváz", "könnyűszerkezet", "szigetelés", "ház"),
    "TimberHaus": ("faház", "faváz", "könnyűszerkezet", "faépítés", "otthon"),
    "RED Property": ("ingatlanfejlesztés", "ingatlan", "beruházás", "értékesítés", "projekt"),
    "Property360": ("ingatlan", "ingatlanüzemeltetés", "értékbecslés", "befektetés", "projekt"),
    "Everyday Homes": ("megfizethető otthon", "családi ház", "praktikus", "építkezés", "otthon"),
    "Venture Studio": ("vállalkozás", "üzletfejlesztés", "innováció", "növekedés", "befektetés"),
    "Family Homes": ("családi ház", "otthon", "alaprajz", "építkezés", "család"),
    "Imperial Construction": ("generálkivitelezés", "építkezés", "kivitelezés", "műszaki", "projekt"),
    "Imperial Intelligence": ("mesterséges intelligencia", "adat", "automatizálás", "kutatás", "döntéstámogatás"),
    "Imperial Technologies": ("technológia", "integráció", "automatizálás", "szoftver", "rendszer"),
    "Imperial Knowledge": ("szakmai tudás", "oktatás", "útmutató", "képzés", "döntés"),
    "ExitFlow": ("cégeladás", "utódlás", "kiszállás", "felvásárlás", "exit"),
    "Veritas Construct": ("műszaki ellenőrzés", "építési vita", "szakértő", "hiba", "kivitelezés"),
    "BauShield": ("építési kockázat", "garancia", "szerződés", "műszaki ellenőrzés", "hiba"),
}

# These copy contracts are deliberately more specific than keyword matching.  They
# are fed to the generator and to the independent release reviewer, so a piece that
# would still work after swapping only the logo must fail closed.
BRAND_PUBLICATION_CONTRACTS = {
    "Imperial": {
        "position": "A cégcsoport átfogó építési és ingatlanos szakmai tekintélye; összetett döntések közérthető, vezetői szintű tisztázása.",
        "voice": "Határozott, természetes, magázó magyar; konkrét helyzet, szakmai álláspont és egyetlen következő lépés.",
        "required": ["építési vagy ingatlanos döntési helyzet", "egyértelmű szakmai álláspont", "konkrét ügyfélhaszon"],
        "forbidden": ["általános motiváció", "másik márka szlogene", "bizonyíték nélküli ár-, idő- vagy garanciaígéret"],
    },
    "Bautica": {
        "position": "Mérnöki fegyelemre épülő felújítás és kivitelezés; a szakmai előkészítés látható előnye.",
        "voice": "Szakértő, világos, tárgyszerű, de értékesítési energiájú magázó magyar.",
        "required": ["valós kivitelezési döntés", "mérnöki ok-okozat", "konkrét ügyfélhaszon"],
        "locked_slogan": "Az építés tudománya.",
        "forbidden": ["általános otthonszépítés", "BauFreund baráti hangja", "bizonyíték nélküli műszaki tény"],
    },
    "Prefab": {
        "position": "Iparosított, előregyártott építési rendszer: tervezhetőség, ismételhetőség és tiszta döntési pontok.",
        "voice": "Modern, tömör, technológiai, közérthető magázó magyar.",
        "required": ["előregyártási vagy szerkezeti mechanizmus", "ügyféloldali döntési előny", "konkrét következő lépés"],
        "locked_slogans": ["Építőipar 2.0", "Nincsenek kérdőjelek."],
        "forbidden": ["általános családiház-szöveg", "favázas életmódhangulat", "nem igazolt gyorsasági állítás"],
    },
    "Casa Moderna": {
        "position": "Kortárs, prémium otthon és építészeti komfort; az átgondolt tér és technológia mindennapi értéke.",
        "voice": "Elegáns, érzékletes, visszafogottan értékesítő magázó magyar.",
        "required": ["konkrét lakóhelyzet", "építészeti vagy komfortdöntés", "prémium ügyfélhaszon"],
        "forbidden": ["olcsóság vagy finanszírozás mint főígéret", "generikus luxusjelzők", "nem igazolt okosotthon-funkció"],
    },
    "BauFreund": {
        "position": "Az építtető barátságos, független szakmai segítője felújításnál, építkezésnél, számításnál és ellenőrzésnél.",
        "voice": "Közvetlen, tegező, természetes, kávé mellett is kimondható magyar.",
        "required": ["felismerhető vevői félelem vagy kérdés", "egy konkrét BauFreund-mechanizmus", "egy megfigyelhető ügyfélhaszon"],
        "locked_slogan": "BauFreund - az építő barát.",
        "forbidden": ["száraz vállalati hang", "Bautica mérnöki-tudomány pozíciója", "általános tanács konkrét ajánlat nélkül"],
    },
    "Danish Fabrik": {
        "position": "Dán szemléletű, iparosított favázas építési rendszer; az anyag- és rendszerválasztás következményei.",
        "voice": "Letisztult, nyugodt, természetes, magázó magyar.",
        "required": ["favázas vagy anyagválasztási döntés", "rendszerszintű ügyfélhaszon", "konkrét következő lépés"],
        "locked_slogan": "Nem érdemes másból építeni.",
        "forbidden": ["TimberHaus választható készültségi mechanizmusa", "romantikus faházleírás", "nem igazolt felsőbbrendűségi tényállítás"],
    },
    "TimberHaus": {
        "position": "Nyíltan összehasonlítható, műszakilag átlátható faépítés és választható kivitelezési készültségi szint.",
        "voice": "Nyugodt, természetes, elemző és következetesen magázó magyar.",
        "required": ["valódi otthon vagy faépítési döntés", "átlátható felelősség vagy készültségi választás", "konkrét következő lépés"],
        "locked_slogan": "Fából mindent lehet.",
        "forbidden": ["Danish életmódhang", "RED agresszív ár-idő hang", "a falszerkezet mint önmagában eladott termék"],
    },
    "RED Property": {
        "position": "Családi házak és típusházak: ár, idő és azonnali összehasonlíthatóság; nem ingatlanközvetítő márka.",
        "voice": "Direkt, energikus, magabiztos, tegező, rövid és félreérthetetlen magyar.",
        "required": ["típusház vagy egyértelmű házválasztási helyzet", "konkrét döntési előny", "egyetlen direkt CTA"],
        "forbidden": ["ingatlanfejlesztés", "ingatlanhirdetés", "közvetítés", "listing", "staging", "bizonyíték nélküli ár-, idő- vagy legjobb/leggyorsabb állítás", "Ház. Ár. Határidő."],
    },
    "Property360": {
        "position": "Az ingatlanvásárlás és beköltözés teljes, összehangolt 360 fokos ügyfélútja; nem befektetési tanácsadás és nem üzemeltetés.",
        "voice": "Segítőkész, lendületes, tegező, döntést könnyítő magyar.",
        "required": ["konkrét lakás- vagy házkeresési helyzet", "összehangolt következő lépés", "kézzelfogható ügyfélhaszon"],
        "locked_slogan": "Kattints és költözz!",
        "forbidden": ["ingatlanbefektetési hozam", "értékbecslés mint főajánlat", "ingatlanüzemeltetés", "általános projektmenedzsment"],
    },
    "Everyday Homes": {
        "position": "Elérhető, praktikus családi otthon és egyszerűbb, egy kézben kezelt megvalósítás.",
        "voice": "Közvetlen, tegező, hétköznapi, reményt adó és konkrét magyar.",
        "required": ["felismerhető családi helyzet", "kézzelfogható otthon- vagy folyamategy­szerűsítési előny", "egy termék- vagy cselekvési CTA"],
        "forbidden": ["bizonyíték nélküli finanszírozási összeg", "Family Homes karakter- és napirend-mechanizmusa", "száraz mérnöki konzultáció mint főtéma"],
    },
    "Family Homes": {
        "position": "A házaknak karakterük van: ház- és alaprajzközpontú történetek arról, milyen benne egy család valódi napja.",
        "voice": "Meleg, megfigyelő, konkrét élethelyzetekből építkező magyar.",
        "required": ["egy házkarakter vagy alaprajzi döntés", "reggel–napközben–este vagy hétvége konkrét használati helyzete", "termékközpontú következő lépés"],
        "forbidden": ["Family Match", "kvíz", "három választásra szűkítés", "finanszírozás vagy megfizethetőség mint főígéret", "Everyday Homes oldal- vagy kérdéslogikája"],
    },
    "Imperial Construction": {
        "position": "Budapesti Magasépítő Vállalat: B2B generálkivitelezés, fővállalkozás és magasépítés szervezett mérnöki színvonalon.",
        "voice": "Tapasztalt cégvezető természetes, magabiztos, magázó hangja.",
        "required": ["generálkivitelezés, fővállalkozás vagy magasépítés kifejezett megnevezése", "konkrét B2B épülettípus vagy növekedési helyzet", "konkrét ajánlatkérési CTA"],
        "forbidden": ["lakossági típusház", "általános projektkontroll mint főígéret", "bizonyíték nélküli 1989-, ár- vagy időgarancia"],
    },
}

# The seven currently internal-only brands still receive daily content, but do not
# have an external delivery target in this release.  Their contract remains explicit
# so their drafts cannot drift into another brand's lane.
for _brand in set(ACTIVE_CONTENT_BRANDS) - set(BRAND_PUBLICATION_CONTRACTS):
    BRAND_PUBLICATION_CONTRACTS[_brand] = {
        "position": ", ".join(BRAND_CONTENT_FOCUS[_brand]),
        "voice": "Természetes, konkrét, szakmai magyar; egy álláspont és egy következő lépés.",
        "required": ["márkaspecifikus probléma", "konkrét ügyfélhaszon", "egyetlen CTA"],
        "forbidden": ["másik Imperial-márka ajánlata", "bizonyíték nélküli szám, ár, idő, garancia vagy felsőfok"],
    }


def delivery_plan_for_brand(brand_id: str) -> dict[str, object]:
    facebook_targets = list(FACEBOOK_TEXT_ONLY_TARGETS.get(brand_id, ()))
    cms_target = CMS_LIVE_TARGETS.get(brand_id)
    return {
        "facebook": {
            "mode": "LIVE_IMAGE_REQUIRED" if facebook_targets else "DISABLED",
            "page_brand_ids": facebook_targets,
            "image_owner": CONTENT_IMAGE_OWNER if facebook_targets else None,
        },
        "cms": {
            "mode": "LIVE_IMAGE_REQUIRED" if cms_target else "DISABLED",
            "site_brand_id": cms_target,
            "image_owner": CONTENT_IMAGE_OWNER if cms_target else None,
        },
    }


def content_focus_for_brand(brand_id: str) -> tuple[str, ...]:
    return BRAND_CONTENT_FOCUS[brand_id]


def publication_contract_for_brand(brand_id: str) -> dict[str, object]:
    return BRAND_PUBLICATION_CONTRACTS[brand_id]

# The canonical hard gate remains ACTIVE / FAIL_CLOSED. Matching content must not be
# queried, fetched, stored, enriched, prompted, handed off, published, or contacted.
NO_MONITORING_HARD_GATE = (
    "Homes4you",
    "HWS Home",
    "Horizont Global",
)

# Owner-mandated land-agent exclusions, approved 2026-08-25. These are evaluated
# independently from scoring and global email suppression. An Otthon Centrum agent
# must carry verified office affiliation so the II./II/A. and XII. district office
# exclusions cannot be bypassed by an incomplete source record.
LAND_AGENT_BLOCKED_OC_OFFICE_ALIASES = (
    "bem rakpart",
    "tdg",
    "hidegkuti ut",
    "lajos utca",
    "uromi utca",
    "mom park",
    "varosmajor utca",
)

LAND_AGENT_HARD_GATE_TURCZER = "land_agent_turczer_jozsef_hard_gate"
LAND_AGENT_HARD_GATE_GDN = "land_agent_gdn_network_hard_gate"
LAND_AGENT_HARD_GATE_OC_II_XII = "land_agent_otthon_centrum_ii_xii_office_hard_gate"
LAND_AGENT_HARD_GATE_OC_UNVERIFIED = "land_agent_otthon_centrum_office_unverified_hard_gate"
LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED = "land_agent_affiliation_unverified_hard_gate"
LAND_AGENT_HARD_GATE_REASONS = frozenset(
    {
        LAND_AGENT_HARD_GATE_TURCZER,
        LAND_AGENT_HARD_GATE_GDN,
        LAND_AGENT_HARD_GATE_OC_II_XII,
        LAND_AGENT_HARD_GATE_OC_UNVERIFIED,
        LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED,
    }
)

ETDR_BRANCHES = (
    "NEW_OR_CHANGED_RECORD_DELTA",
    "ETDR_START_NOT_VERIFIED",
    "ETDR_COMPLETION_NOT_VERIFIED",
)


@dataclass(frozen=True)
class DailyGateResult:
    route_attempts: int
    unique_leads: int
    question_topics: int
    content_brands: int

    @property
    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.route_attempts < DAILY_ROUTE_ATTEMPT_MINIMUM:
            errors.append("route_attempt_minimum_not_met")
        if self.unique_leads < DAILY_UNIQUE_LEAD_MINIMUM:
            errors.append("unique_lead_minimum_not_met")
        if self.question_topics < DAILY_QUESTION_TOPIC_MINIMUM:
            errors.append("question_topic_minimum_not_met")
        if self.content_brands < DAILY_CONTENT_BRAND_MINIMUM:
            errors.append("all_brand_content_minimum_not_met")
        return tuple(errors)

    @property
    def passed(self) -> bool:
        return not self.errors


def assert_policy_integrity() -> None:
    anchors = (
        (PARTNER_OUTREACH_ANCHOR, PARTNER_OUTREACH_ANCHOR_SHA256),
        (LAND_OWNER_SUBJECT, LAND_OWNER_SUBJECT_SHA256),
        (LAND_AGENT_SUBJECT, LAND_AGENT_SUBJECT_SHA256),
        (LAND_OUTREACH_SERVICE_ANCHOR, LAND_OUTREACH_SERVICE_ANCHOR_SHA256),
        (LAND_AGENT_COMMISSION_ANCHOR, LAND_AGENT_COMMISSION_ANCHOR_SHA256),
        (LAND_OWNER_FREE_AD_ANCHOR, LAND_OWNER_FREE_AD_ANCHOR_SHA256),
        (LAND_OWNER_SERVICE_ANCHOR, LAND_OWNER_SERVICE_ANCHOR_SHA256),
        (LAND_OWNER_PERMISSION_ANCHOR, LAND_OWNER_PERMISSION_ANCHOR_SHA256),
        (LAND_OWNER_REPLY_ANCHOR, LAND_OWNER_REPLY_ANCHOR_SHA256),
    )
    if any(
        hashlib.sha256(value.encode("utf-8")).hexdigest() != expected
        for value, expected in anchors
    ):
        raise RuntimeError("Owner-approved outreach anchor integrity check failed")
    if len(ACTIVE_CONTENT_BRANDS) != DAILY_CONTENT_BRAND_MINIMUM:
        raise RuntimeError("Canonical active-brand count is inconsistent")
    if len(set(ACTIVE_CONTENT_BRANDS)) != len(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("Canonical active-brand list contains duplicates")
    if not set(FACEBOOK_TEXT_ONLY_TARGETS).issubset(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("Facebook delivery scope references an inactive content brand")
    if not set(CMS_LIVE_TARGETS).issubset(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("CMS delivery scope references an inactive content brand")
    page_targets = [
        page_id
        for page_ids in FACEBOOK_TEXT_ONLY_TARGETS.values()
        for page_id in page_ids
    ]
    if len(page_targets) != 12 or len(set(page_targets)) != 12:
        raise RuntimeError("Facebook delivery scope must contain exactly 12 unique pages")
    if len(CMS_LIVE_TARGETS) != 5:
        raise RuntimeError("CMS delivery scope must contain exactly five verified sites")
    if set(BRAND_CONTENT_FOCUS) != set(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("Every active content brand must have an explicit topic focus")
    if set(BRAND_PUBLICATION_CONTRACTS) != set(ACTIVE_CONTENT_BRANDS):
        raise RuntimeError("Every active content brand must have a publication contract")


def assert_outreach_copy(body: str) -> None:
    assert_policy_integrity()
    if LAND_OUTREACH_SERVICE_ANCHOR in body:
        has_agent_offer = LAND_AGENT_COMMISSION_ANCHOR in body
        if not has_agent_offer or LAND_OWNER_FREE_AD_ANCHOR in body:
            raise ValueError("owner_locked_land_outreach_offer_missing_or_mixed")
        return
    if LAND_OWNER_SERVICE_ANCHOR in body:
        required = (
            LAND_OWNER_FREE_AD_ANCHOR,
            LAND_OWNER_PERMISSION_ANCHOR,
            LAND_OWNER_REPLY_ANCHOR,
        )
        if (
            not all(anchor in body for anchor in required)
            or LAND_AGENT_COMMISSION_ANCHOR in body
        ):
            raise ValueError("owner_locked_land_outreach_offer_missing_or_mixed")
        return
    if PARTNER_OUTREACH_ANCHOR not in body:
        raise ValueError("owner_locked_partner_outreach_anchor_missing")

def contains_no_monitoring_entity(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return any(name.casefold() in normalized for name in NO_MONITORING_HARD_GATE)


def _identity_fold(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_like = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_like.casefold()).split())


def _blocked_oc_office(office_name: str) -> bool:
    normalized = _identity_fold(office_name)
    district_pattern = re.compile(
        r"\b(?:ii(?:\s*a)?|2(?:\s*a)?|xii|12)\s+kerulet(?:i)?\b|"
        r"\b(?:2|12)\s*ker\b"
    )
    if district_pattern.search(normalized):
        return True
    if normalized.strip() in {"ii", "ii a", "iia", "xii"}:
        return True
    if re.search(r"\b(?:102\d|112\d)\b", normalized):
        return True
    return any(alias in normalized for alias in LAND_AGENT_BLOCKED_OC_OFFICE_ALIASES)


def land_agent_hard_gate_reason(
    *,
    recipient_role: str,
    contact_name: str | None,
    organization_name: str | None,
    office_name: str | None,
    recipient_email: str | None,
    public_contact_url: str | None,
    evidence_url: str | None,
) -> str | None:
    """Return a non-overridable exclusion reason for a land-listing agent."""

    if recipient_role != "listing_agent":
        return None
    identity = _identity_fold(
        " ".join(
            value
            for value in (
                contact_name,
                organization_name,
                office_name,
                recipient_email,
                public_contact_url,
                evidence_url,
            )
            if value
        )
    )
    if re.search(r"\b(?:turczer\s+jozsef|jozsef\s+turczer)\b", identity):
        return LAND_AGENT_HARD_GATE_TURCZER
    if re.search(r"\bg\s*d\s*n\b", identity):
        return LAND_AGENT_HARD_GATE_GDN
    if not organization_name or not organization_name.strip():
        return LAND_AGENT_HARD_GATE_AFFILIATION_UNVERIFIED
    is_otthon_centrum = bool(
        re.search(r"\botthon\s+centrum\b|\boc\s+hu\b", identity)
    )
    if not is_otthon_centrum:
        return None
    if not office_name or not office_name.strip():
        return LAND_AGENT_HARD_GATE_OC_UNVERIFIED
    if _blocked_oc_office(office_name):
        return LAND_AGENT_HARD_GATE_OC_II_XII
    return None


assert_policy_integrity()
