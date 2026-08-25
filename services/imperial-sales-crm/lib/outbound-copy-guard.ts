export type OutboundCopyKind = "outreach" | "followup" | "transactional" | "internal";

const foreignBrandAliases: Record<string, string[]> = {
  "imperial-holding": ["imperial holding"],
  "imperial-intelligence": ["imperial intelligence"],
  "imperial-construction": ["imperial construction"],
  "imperial-knowledge": ["imperial knowledge"],
  "imperial-technologies": ["imperial technologies"],
  "imperial-venture-studio": ["imperial venture studio"],
  property360: ["property360", "property 360"],
  baushield: ["baushield", "bau shield"],
  bautica: ["bautica"],
  prefab: ["prefab"],
  exitflow: ["exitflow", "exit flow"],
  veritas: ["veritas construct", "veritas"],
  baufreund: ["baufreund", "bau freund"],
  "danish-fabrik": ["danish fabrik"],
  timberhaus: ["timberhaus", "timber haus"],
  "casa-moderna": ["casa moderna", "casa moderna living"],
  "everyday-homes": ["everyday homes", "everyday homes stories"],
  "family-homes": ["family homes", "family homes családi magazin"],
  "budapesti-magasepito-vallalat": ["budapesti magasépítő vállalat", "budapesti magasepito vallalat"],
  "red-property": ["red property", "red property report"],
};

const brandDomains: Record<string, string[]> = {
  "imperial-holding": ["imperialholding.hu", "myimperial.hu"],
  "imperial-intelligence": ["imperialintelligence.hu"],
  "imperial-construction": ["imperialconstruction.hu"],
  "imperial-knowledge": ["imperialknowledge.hu"],
  "imperial-technologies": ["imperialtechnologies.hu"],
  "imperial-venture-studio": ["imperialventurestudio.hu"],
  property360: ["property360.hu"],
  baushield: ["baushield.hu"],
  bautica: ["bautica.hu", "bautica.test"],
  prefab: ["prefab.hu"],
  exitflow: ["exitflow.hu"],
  veritas: ["veritasconstruct.hu"],
  baufreund: ["baufreund.hu"],
  "danish-fabrik": ["danishfabrik.hu"],
  timberhaus: ["timberhaus.hu"],
  "casa-moderna": ["casamoderna.hu"],
  "everyday-homes": ["everydayhomes.hu"],
  "family-homes": ["familyhomes.hu"],
  "budapesti-magasepito-vallalat": ["budapestimagasepito.hu"],
  "red-property": ["redproperty.hu"],
};

const jargon = [
  "workflow", "pipeline", "handoff", "routing", "route", "checkpoint", "run", "ledger",
  "dashboard", "lifecycle", "funnel", "stakeholder", "lead scoring", "lead", "lead generator",
  "leadgenerátor", "lead generátor", "outreach", "pilot", "opt-in", "referral", "landing", "readback",
  "budget-check", "value engineering", "due diligence", "white-label", "oem", "sla",
  "fit-out", "triázs", "partnercsatorna", "munkacsomag", "bom", "dfma", "projectcanary", "deduplikáció", "kompetenciaalapú hozzárendelés",
  "projektjel-feldolgozás", "strukturált együttműködés", "ügyfélvédelmi keretek",
  "korai fejlesztési jel", "auditigény", "audit igény",
  "eszkaláció",
  "api", "backend", "frontend", "endpoint", "deployment", "deploy", "sprint",
  "ticket", "task", "scope", "backlog", "milestone", "roadmap", "stack",
  "framework", "interface", "webhook", "payload", "prompt", "rollout", "release",
  "checklist", "projektmenedzsment", "projektmenedzser", "projekt manager",
  "projektkontroll", "projektirányítás", "projektfigyelő rendszer", "integráció",
  "automatizáció", "orchestration", "orchesztráció", "partnerattribúció",
  "attribúció", "delivery modell", "raw adatbázis", "státusz",
];

const jargonPatterns: Array<[RegExp, string]> = [
  [/(^|[^a-z0-9áéíóöőúüű_])strukturált(?:\s+[a-z0-9áéíóöőúüű_-]+){0,2}\s+együttműköd[a-z0-9áéíóöőúüű_-]*/i, "strukturált együttműködés"],
  [/(^|[^a-z0-9áéíóöőúüű_])projektjel[- ]feldolgoz[a-z0-9áéíóöőúüű_-]*/i, "projektjel-feldolgozás"],
  [/(^|[^a-z0-9áéíóöőúüű_])ügyfélvédelmi\s+keret[a-z0-9áéíóöőúüű_-]*/i, "ügyfélvédelmi keretek"],
  [/(^|[^a-z0-9áéíóöőúüű_])korai\s+fejlesztési\s+jel[a-z0-9áéíóöőúüű_-]*/i, "korai fejlesztési jel"],
  [/(^|[^a-z0-9áéíóöőúüű_])audit[- ]?igény[a-z0-9áéíóöőúüű_-]*/i, "auditigény"],
  [/(^|[^a-z0-9áéíóöőúüű_])deduplik[a-z0-9áéíóöőúüű_-]*/i, "deduplikáció"],
  [/(^|[^a-z0-9áéíóöőúüű_])partnercsatorn[a-z0-9áéíóöőúüű_-]*/i, "partnercsatorna"],
  [/(^|[^a-z0-9áéíóöőúüű_])kompetencia\s+alapján\s+rendel[a-z0-9áéíóöőúüű_-]*/i, "kompetencia alapján rendel"],
  [/(^|[^a-z0-9áéíóöőúüű_])lead(?:ek|et|eket|nek|del|ből|re|lista|listát|generátor|generátort|generátorral)?($|[^a-z0-9áéíóöőúüű_])/i, "lead"],
  [/(^|[^a-z0-9áéíóöőúüű_])(?:pilot|outreach|routing|pipeline|triázs|munkacsomag|projectcanary)[a-z0-9áéíóöőúüű_-]*/i, "külső szakzsargon"],
];

const nextStepMarkers = [
  "kérjük", "válaszoljon", "válaszoljanak", "írjon", "írják", "egyeztessünk",
  "egyeztethetünk", "időpont", "hívjon", "küldje", "küldjék", "adja meg",
  "adják meg", "nyissa meg", "nyissák meg", "fogadja el", "elfogadása", "megnyitása",
];

const purposeMarkers = [
  "szeretnénk", "keressük", "keresünk", "felajánljuk", "fel tudunk ajánlani",
  "kínálunk", "segítünk", "meghívjuk", "azért írunk", "visszatérünk",
];

const benefitMarkers = [
  "tudunk segíteni", "segítünk önnek", "segítünk önöknek", "ez segít önnek",
  "ez segít önöknek", "jutalék", "megbízási lehetőség", "új megbízás",
  "kapacitást tudunk adni", "kapacitásunkat felajánljuk",
  "kapacitásunkat szeretnénk felajánlani", "fel tudunk ajánlani",
  "előnyt jelent", "előnyös önnek", "előnyös önöknek", "időt takarít meg",
  "költséget takarít meg",
];

const hungarianSuffix = "(?:t|ot|et|öt|at|k|ok|ek|ök|ak|okat|eket|öket|akat|nak|nek|ban|ben|ba|be|ból|ből|hoz|hez|höz|ról|ről|tól|től|ra|re|ért|ig|ként|on|en|ön|n|nál|nél|ja|je|juk|jük|os|es|ös|i|val|vel|[bcdfghjklmnpqrstvwxyz](?:al|el))";

function normalize(value: string) {
  return value.normalize("NFKC").toLocaleLowerCase("hu-HU").replace(/\s+/g, " ").trim();
}

function containsPhrase(text: string, phrase: string) {
  const escaped = normalize(phrase).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    `(^|[^a-z0-9áéíóöőúüű_])${escaped}($|[^a-z0-9áéíóöőúüű_])`,
    "i",
  ).test(text);
}

function containsInflectedPhrase(text: string, phrase: string) {
  const normalized = normalize(phrase);
  const variants = [normalized];
  if (normalized.endsWith("a")) variants.push(`${normalized.slice(0, -1)}á`);
  if (normalized.endsWith("e")) variants.push(`${normalized.slice(0, -1)}é`);
  const alternatives = [...new Set(variants)]
    .map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  return new RegExp(
    `(^|[^a-z0-9áéíóöőúüű_])(?:${alternatives})(?:-?${hungarianSuffix})?($|[^a-z0-9áéíóöőúüű_])`,
    "i",
  ).test(text);
}

function wordCount(value: string) {
  return value.match(/[a-z0-9áéíóöőúüű_]+/gi)?.length ?? 0;
}

function decodeHtmlEntities(value: string) {
  const named: Record<string, string> = {
    amp: "&", apos: "'", gt: ">", lt: "<", nbsp: " ", quot: '"',
  };
  return value.replace(/&#(x[0-9a-f]+|\d+);|&([a-z]+);/gi, (match, numeric, name) => {
    if (numeric) {
      const codePoint = numeric[0].toLowerCase() === "x"
        ? Number.parseInt(numeric.slice(1), 16)
        : Number.parseInt(numeric, 10);
      return Number.isSafeInteger(codePoint) && codePoint > 0 && codePoint <= 0x10ffff
        ? String.fromCodePoint(codePoint)
        : " ";
    }
    return named[String(name).toLowerCase()] ?? match;
  });
}

function visibleHtml(value: string) {
  return decodeHtmlEntities(value.replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
    .replace(/<br\s*\/?>|<\/(?:p|div|li|h[1-6]|tr)>/gi, "\n\n")
    .replace(/<[^>]+>/g, " "));
}

function senderIdentity(fromEmail: string) {
  const trimmed = fromEmail.trim();
  const angleAddress = trimmed.match(/<([^<>]+)>\s*$/)?.[1];
  const displayName = angleAddress ? trimmed.slice(0, trimmed.lastIndexOf("<")).trim() : "";
  const address = (angleAddress ?? trimmed).toLocaleLowerCase("en-US");
  const parts = address.split("@");
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    throw new Error("OUTBOUND_COPY_BLOCKED:sender_email_invalid");
  }
  const domain = parts[1].replace(/\.$/, "");
  if (!/^[a-z0-9.-]+$/.test(domain) || domain.includes("..")) {
    throw new Error("OUTBOUND_COPY_BLOCKED:sender_email_invalid");
  }
  return { displayName, domain };
}

function domainMatches(domain: string, allowed: string) {
  return domain === allowed || domain.endsWith(`.${allowed}`);
}

function brandFromSender(fromEmail: string) {
  const { displayName, domain } = senderIdentity(fromEmail);
  for (const [brand, domains] of Object.entries(brandDomains)) {
    if (domains.some((allowed) => domainMatches(domain, allowed))) {
      const allowedDisplayNames = foreignBrandAliases[brand] ?? [];
      if (displayName && !allowedDisplayNames.some((alias) => normalize(displayName) === normalize(alias))) {
        throw new Error("OUTBOUND_COPY_BLOCKED:sender_brand_mismatch");
      }
      return brand;
    }
  }
  throw new Error("OUTBOUND_COPY_BLOCKED:sender_brand_unknown");
}

function detectedLinkBrands(value: string) {
  const found = new Set<string>();
  const normalized = value.toLocaleLowerCase("en-US");
  for (const [brand, domains] of Object.entries(brandDomains)) {
    for (const domain of domains) {
      const escaped = domain.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const pattern = new RegExp(
        `(^|[^a-z0-9.-])(?:[a-z0-9-]+\\.)*${escaped}(?![a-z0-9-]|\\.[a-z0-9-])`,
        "i",
      );
      if (pattern.test(normalized)) {
        found.add(brand);
        break;
      }
    }
  }
  return found;
}

function actionSegmentCount(body: string) {
  return body.replace(/https?:\/\/\S+/g, "").split(/[.!?]+(?:\s+|$)|\n\s*\n+/)
    .map(normalize)
    .filter((segment) => segment && !segment.startsWith("leiratkoz") && !segment.includes("ha nem kíván"))
    .filter((segment) => nextStepMarkers.some((marker) => containsPhrase(segment, marker))).length;
}

export function validateOutboundEmail(input: {
  fromEmail: string;
  subject: string;
  text: string;
  html?: string;
  replyToEmail?: string;
  kind?: OutboundCopyKind;
}) {
  const kind = input.kind ?? "transactional";
  const brand = brandFromSender(input.fromEmail);
  if (input.replyToEmail && brandFromSender(input.replyToEmail) !== brand) {
    throw new Error("OUTBOUND_COPY_BLOCKED:reply_to_brand_mismatch");
  }
  const htmlText = visibleHtml(input.html ?? "");
  const fullText = normalize(`${input.subject}\n${input.text}\n${htmlText}`);
  const errors: string[] = [];

  if (!input.subject.trim()) errors.push("subject_missing");
  if (wordCount(input.subject) > 8) errors.push("subject_over_8_words");
  const bodyLimit = kind === "outreach" ? 120 : kind === "followup" ? 80 : 180;
  const bodies = [input.text, htmlText].filter((body) => body.trim());
  if (!bodies.length) errors.push("body_missing");
  for (const body of bodies) {
    if (wordCount(body) > bodyLimit) errors.push(`body_over_${bodyLimit}_words`);
    const sentenceLengths = body.replace(/https?:\/\/\S+/g, "")
      .split(/[.!?]+(?:\s+|$)|\n\s*\n+/).filter(Boolean).map(wordCount);
    if (sentenceLengths.some((length) => length > 25)) errors.push("sentence_over_25_words");
    const normalizedBody = normalize(body);
    if (!purposeMarkers.some((marker) => containsPhrase(normalizedBody, marker))) {
      errors.push("purpose_not_clear");
    }
    if (!benefitMarkers.some((marker) => containsInflectedPhrase(normalizedBody, marker))) {
      errors.push("recipient_benefit_not_clear");
    }
    const actions = actionSegmentCount(body);
    if (!actions) errors.push("next_step_not_clear");
    if (actions > 1) errors.push("multiple_next_steps");
  }

  const foundJargon = [...new Set([
    ...jargon.filter((phrase) => containsInflectedPhrase(fullText, phrase)),
    ...jargonPatterns.filter(([pattern]) => pattern.test(fullText)).map(([, label]) => label),
  ])];
  if (foundJargon.length) errors.push(`jargon:${foundJargon.sort().join("|")}`);
  const detectedBrands = new Set(Object.entries(foreignBrandAliases)
    .filter(([, aliases]) => aliases.some((alias) => containsInflectedPhrase(fullText, alias)))
    .map(([candidate]) => candidate));
  for (const linkedBrand of detectedLinkBrands(`${input.subject}\n${input.text}\n${input.html ?? ""}`)) {
    detectedBrands.add(linkedBrand);
  }
  if (!detectedBrands.has(brand)) errors.push("expected_brand_missing");
  const foreignBrands = [...detectedBrands]
    .filter((candidate) => candidate !== brand)
    .sort();
  if (foreignBrands.length) errors.push(`foreign_brand:${foreignBrands.join("|")}`);
  const uniqueErrors = [...new Set(errors)];
  if (uniqueErrors.length) throw new Error(`OUTBOUND_COPY_BLOCKED:${uniqueErrors.join(",")}`);
}
