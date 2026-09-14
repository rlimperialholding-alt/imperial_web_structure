import type {
  IngestionDecision,
  SourceEvent,
  TaskCandidate,
} from "./types.js";

export interface IngestionRule {
  name: string;
  evaluate(event: SourceEvent): IngestionDecision | null;
}

const P1_TERMS = [
  "nav",
  "adóhatóság",
  "hatósági",
  "jogi felszólítás",
  "fizetési felszólítás",
  "szerződésszegés",
  "felmondás",
  "banki határidő",
  "könyvelési határidő",
  "ügyfélpanasz",
  "kártérítés",
];

const ACTION_TERMS = [
  "kérem",
  "kérjük",
  "szükséges",
  "küldd",
  "küldje",
  "válaszolj",
  "válaszoljon",
  "határidő",
  "jóváhagyás",
  "aláírás",
  "egyeztetés",
  "teendő",
  "intézni",
];

export class CriticalMailRule implements IngestionRule {
  readonly name = "critical-mail";

  evaluate(event: SourceEvent): IngestionDecision | null {
    if (event.source !== "GMAIL") return null;
    const text = searchable(event);
    const matched = P1_TERMS.filter((term) => text.includes(term));
    if (matched.length === 0) return null;

    const candidate = baseCandidate(event, {
      priority: "P1",
      sensitivity: inferSensitivity(text),
      confidence: 0.94,
      requiresHumanReview: false,
      reasons: [`Kritikus kifejezések: ${matched.join(", ")}`],
    });

    return {
      action: "CREATE_TASK",
      candidate,
      reason: "Kritikus üzleti vagy hatósági e-mail.",
    };
  }
}

export class ActionRequestMailRule implements IngestionRule {
  readonly name = "action-request-mail";

  evaluate(event: SourceEvent): IngestionDecision | null {
    if (event.source !== "GMAIL") return null;
    const text = searchable(event);
    const matched = ACTION_TERMS.filter((term) => text.includes(term));
    if (matched.length === 0) return null;

    const confidence = Math.min(0.9, 0.55 + matched.length * 0.08);
    const candidate = baseCandidate(event, {
      priority: text.includes("sürgős") ? "P1" : "P2",
      sensitivity: inferSensitivity(text),
      confidence,
      requiresHumanReview: confidence < 0.75,
      reasons: [`Cselekvést kérő kifejezések: ${matched.join(", ")}`],
    });

    return {
      action: candidate.requiresHumanReview
        ? "HUMAN_REVIEW"
        : "CREATE_TASK",
      candidate,
      reason: "Az e-mail végrehajtandó kérést tartalmaz.",
    };
  }
}

export class CalendarCommitmentRule implements IngestionRule {
  readonly name = "calendar-commitment";

  evaluate(event: SourceEvent): IngestionDecision | null {
    if (event.source !== "CALENDAR") return null;
    const text = searchable(event);
    const commitment =
      text.includes("határidő") ||
      text.includes("leadás") ||
      text.includes("jóváhagyás") ||
      text.includes("döntés") ||
      text.includes("follow-up") ||
      text.includes("utánkövetés");

    if (!commitment) return null;

    const dueAt = parseMetadataDate(event.metadata.startAt);
    const candidate = baseCandidate(event, {
      priority: text.includes("sürgős") ? "P1" : "P2",
      sensitivity: inferSensitivity(text),
      confidence: 0.82,
      requiresHumanReview: false,
      reasons: ["A naptári esemény konkrét kötelezettséget jelez."],
      ...(dueAt ? { dueAt } : {}),
    });

    return {
      action: "CREATE_TASK",
      candidate,
      reason: "Naptári kötelezettségből feladat keletkezik.",
    };
  }
}

export class IgnoreNoiseRule implements IngestionRule {
  readonly name = "ignore-noise";

  evaluate(event: SourceEvent): IngestionDecision | null {
    const text = searchable(event);
    const noise =
      event.labels.includes("SPAM") ||
      event.labels.includes("TRASH") ||
      text.includes("unsubscribe") ||
      text.includes("leiratkozás") ||
      text.includes("automatikus válasz") ||
      text.includes("out of office");

    return noise
      ? { action: "IGNORE", reason: "Nem végrehajtási jellegű vagy zajos esemény." }
      : null;
  }
}

export class IngestionRuleEngine {
  constructor(private readonly rules: IngestionRule[]) {}

  evaluate(event: SourceEvent): IngestionDecision {
    for (const rule of this.rules) {
      const result = rule.evaluate(event);
      if (result) return result;
    }
    return {
      action: "IGNORE",
      reason: "Nem azonosítható kellő bizonyosságú végrehajtási kötelezettség.",
    };
  }
}

export function defaultIngestionRules(): IngestionRule[] {
  return [
    new IgnoreNoiseRule(),
    new CriticalMailRule(),
    new ActionRequestMailRule(),
    new CalendarCommitmentRule(),
  ];
}

function baseCandidate(
  event: SourceEvent,
  overrides: Partial<TaskCandidate>,
): TaskCandidate {
  return {
    sourceEventId: event.id,
    organizationId: event.organizationId,
    source: event.source,
    sourceExternalId: event.externalId,
    title: event.subject?.trim() || "Forráseseményből létrehozott feladat",
    description: event.body?.trim() || event.subject || "Nincs további leírás.",
    issuerId: event.actorId ?? "digital-anne",
    priority: "P2",
    dueAt: defaultDueAt(event),
    acceptanceCriteria:
      "A kért intézkedés végrehajtva és ellenőrizhető bizonyítékkal alátámasztva.",
    evidenceDescription:
      "Válasz-email, jóváhagyott dokumentum vagy rendszeradat.",
    contactEmail: event.participants[0],
    confidence: 0.7,
    requiresHumanReview: true,
    reasons: [],
    sensitivity: "INTERNAL",
    ...overrides,
  };
}

function defaultDueAt(event: SourceEvent): Date {
  const due = new Date(event.occurredAt);
  due.setUTCDate(due.getUTCDate() + 2);
  return due;
}

function searchable(event: SourceEvent): string {
  return `${event.subject ?? ""}\n${event.body ?? ""}`
    .toLowerCase()
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "");
}

function inferSensitivity(
  text: string,
): TaskCandidate["sensitivity"] {
  if (text.includes("nav") || text.includes("hatóság")) return "AUTHORITY";
  if (text.includes("jogi") || text.includes("szerződés")) return "LEGAL";
  if (
    text.includes("bank") ||
    text.includes("számla") ||
    text.includes("adó")
  ) return "FINANCIAL";
  if (text.includes("munkavállaló") || text.includes("hr")) return "HR";
  return "INTERNAL";
}

function parseMetadataDate(value: unknown): Date | undefined {
  if (typeof value !== "string") return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}
