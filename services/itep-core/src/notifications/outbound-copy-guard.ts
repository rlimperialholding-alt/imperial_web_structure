const brandAliases: Record<string, string[]> = {
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

const brandIdAliases: Record<string, string> = {
  imperial: "imperial-holding",
  imperialholding: "imperial-holding",
  danishfabrik: "danish-fabrik",
  casamoderna: "casa-moderna",
  everydayhomes: "everyday-homes",
  familyhomes: "family-homes",
  budapestimagasepito: "budapesti-magasepito-vallalat",
  "budapesti-magasepito": "budapesti-magasepito-vallalat",
  redproperty: "red-property",
  "property-360": "property360",
  "veritas-construct": "veritas",
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
  [/(^|[^\p{L}\p{N}_])strukturált(?:\s+[\p{L}\p{N}_-]+){0,2}\s+együttműköd[\p{L}\p{N}_-]*/u, "strukturált együttműködés"],
  [/(^|[^\p{L}\p{N}_])projektjel[- ]feldolgoz[\p{L}\p{N}_-]*/u, "projektjel-feldolgozás"],
  [/(^|[^\p{L}\p{N}_])ügyfélvédelmi\s+keret[\p{L}\p{N}_-]*/u, "ügyfélvédelmi keretek"],
  [/(^|[^\p{L}\p{N}_])korai\s+fejlesztési\s+jel[\p{L}\p{N}_-]*/u, "korai fejlesztési jel"],
  [/(^|[^\p{L}\p{N}_])audit[- ]?igény[\p{L}\p{N}_-]*/u, "auditigény"],
  [/(^|[^\p{L}\p{N}_])deduplik[\p{L}\p{N}_-]*/u, "deduplikáció"],
  [/(^|[^\p{L}\p{N}_])partnercsatorn[\p{L}\p{N}_-]*/u, "partnercsatorna"],
  [/(^|[^\p{L}\p{N}_])kompetencia\s+alapján\s+rendel[\p{L}\p{N}_-]*/u, "kompetencia alapján rendel"],
  [/(^|[^\p{L}\p{N}_])lead(?:ek|et|eket|nek|del|ből|re|lista|listát|generátor|generátort|generátorral)?($|[^\p{L}\p{N}_])/u, "lead"],
  [/(^|[^\p{L}\p{N}_])(?:pilot|outreach|routing|pipeline|triázs|munkacsomag|projectcanary)[\p{L}\p{N}_-]*/u, "külső szakzsargon"],
];

const nextSteps = [
  "kérjük", "válaszoljon", "válaszoljanak", "írjon", "írják", "egyeztessünk",
  "egyeztethetünk", "időpont", "hívjon", "küldje", "küldjék", "adja meg",
  "adják meg", "nyissa meg", "nyissák meg", "fogadja el", "végezze el",
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
  return new RegExp(`(^|[^\\p{L}\\p{N}_])${escaped}($|[^\\p{L}\\p{N}_])`, "u").test(text);
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
    `(^|[^\\p{L}\\p{N}_])(?:${alternatives})(?:-?${hungarianSuffix})?($|[^\\p{L}\\p{N}_])`,
    "u",
  ).test(text);
}

function wordCount(value: string) {
  return value.match(/[\p{L}\p{N}_]+/gu)?.length ?? 0;
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

function senderIdentity(senderEmail: string) {
  const trimmed = senderEmail.trim();
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

export function classifyRecipientAudience(
  brandId: string,
  recipientEmail: string,
): "external" | "internal" {
  const requestedBrand = brandId.replace(/_/g, "-").toLocaleLowerCase("hu-HU");
  const expectedBrand = brandIdAliases[requestedBrand] ?? requestedBrand;
  const allowedDomains = brandDomains[expectedBrand];
  if (!allowedDomains) return "external";
  try {
    const { domain } = senderIdentity(recipientEmail);
    return allowedDomains.some((allowed) => domainMatches(domain, allowed))
      ? "internal"
      : "external";
  } catch {
    return "external";
  }
}

function brandFromSender(senderEmail: string) {
  const { displayName, domain } = senderIdentity(senderEmail);
  for (const [brand, domains] of Object.entries(brandDomains)) {
    if (domains.some((allowed) => domainMatches(domain, allowed))) {
      const allowedDisplayNames = brandAliases[brand] ?? [];
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
    .filter((segment) => nextSteps.some((marker) => containsPhrase(segment, marker))).length;
}

export function validateOutboundCopy(input: {
  brandId: string;
  senderEmail: string;
  subject: string;
  text: string;
  html?: string;
  replyToEmail?: string;
  audience?: "external" | "internal";
}) {
  const requestedBrand = input.brandId.replace(/_/g, "-").toLocaleLowerCase("hu-HU");
  const expectedBrand = brandIdAliases[requestedBrand] ?? requestedBrand;
  if (!brandAliases[expectedBrand]) throw new Error("OUTBOUND_COPY_BLOCKED:sender_brand_unknown");
  if (brandFromSender(input.senderEmail) !== expectedBrand) {
    throw new Error("OUTBOUND_COPY_BLOCKED:sender_brand_mismatch");
  }
  if (input.replyToEmail && brandFromSender(input.replyToEmail) !== expectedBrand) {
    throw new Error("OUTBOUND_COPY_BLOCKED:reply_to_brand_mismatch");
  }
  const htmlText = visibleHtml(input.html ?? "");
  const fullText = normalize(`${input.subject}\n${input.text}\n${htmlText}`);
  const errors: string[] = [];

  if (!input.subject.trim()) errors.push("subject_missing");
  if (wordCount(input.subject) > 8) errors.push("subject_over_8_words");
  const wordLimit = input.audience === "external" ? 120 : 180;
  const bodies = [input.text, htmlText].filter((body) => body.trim());
  if (!bodies.length) errors.push("body_missing");
  for (const body of bodies) {
    if (wordCount(body) > wordLimit) errors.push(`body_over_${wordLimit}_words`);
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
  const detectedBrands = new Set(Object.entries(brandAliases)
    .filter(([, aliases]) => aliases.some((alias) => containsInflectedPhrase(fullText, alias)))
    .map(([brand]) => brand));
  for (const linkedBrand of detectedLinkBrands(`${input.subject}\n${input.text}\n${input.html ?? ""}`)) {
    detectedBrands.add(linkedBrand);
  }
  if (!detectedBrands.has(expectedBrand)) errors.push("expected_brand_missing");
  const foreignBrands = [...detectedBrands].filter((brand) => brand !== expectedBrand).sort();
  if (foreignBrands.length) errors.push(`foreign_brand:${foreignBrands.join("|")}`);
  const uniqueErrors = [...new Set(errors)];
  if (uniqueErrors.length) throw new Error(`OUTBOUND_COPY_BLOCKED:${uniqueErrors.join(",")}`);
}
