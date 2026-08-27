import type { CreateTaskInput } from "../application/task-service.js";

export type EnterpriseEventType =
  | "CONTRACT_SIGNED"
  | "PAYMENT_DUE"
  | "CHANGE_APPROVED"
  | "QUALITY_CHECK_FAILED";

export interface EnterpriseDomainEvent {
  organizationId: string;
  source: string;
  externalEventId: string;
  eventType: EnterpriseEventType;
  projectId: string;
  ownerId: string;
  occurredAt: Date;
  dueAt?: Date;
  title?: string;
  payload: Record<string, unknown>;
}

export interface OrchestrationDefaults {
  issuerId: string;
  escalationPersonId: string;
  contactEmail: string;
}

const DAY = 24 * 60 * 60 * 1000;

export function buildWorkflowTasks(
  event: EnterpriseDomainEvent,
  defaults: OrchestrationDefaults,
  now = new Date(),
): CreateTaskInput[] {
  const common = {
    organizationId: event.organizationId,
    source: "SMART_CALENDAR",
    issuerId: defaults.issuerId,
    assigneeId: event.ownerId,
    assigneeType: "EMPLOYEE" as const,
    escalationPersonId: defaults.escalationPersonId,
    contact: { email: defaults.contactEmail },
    relatedEntityIds: [event.projectId],
    dependencies: [],
  };
  const due = event.dueAt ?? new Date(Math.max(now.getTime(), event.occurredAt.getTime()) + DAY);

  if (event.eventType === "CONTRACT_SIGNED") {
    return [
      {
        ...common,
        sourceExternalId: `${event.externalEventId}:project-start`,
        title: event.title ?? "Projektindítás aláírt szerződésből",
        description: "Hozd létre a projektindítási rendet és rendeld hozzá a felelősöket.",
        priority: "P1",
        dueAt: due,
        acceptanceCriteria: "A projektazonosító, felelős, kezdési feltételek és első mérföldkövek rögzítve.",
        evidenceRequirement: { type: "SYSTEM_DATA", description: "Projektindítási rendszerbejegyzés", machineVerifiable: true },
        sensitivity: "LEGAL",
      },
      {
        ...common,
        sourceExternalId: `${event.externalEventId}:document-check`,
        title: "Szerződéses dokumentumcsomag teljességi ellenőrzése",
        description: "Ellenőrizd a szerződést, mellékleteket, Ártükröt és Ütemtükröt.",
        priority: "P2",
        dueAt: due,
        acceptanceCriteria: "Minden kötelező irat verzióazonosítóval elérhető vagy hiányfeladat készült.",
        evidenceRequirement: { type: "DOCUMENT", description: "Ellenőrzött dokumentumlista", machineVerifiable: false },
        sensitivity: "LEGAL",
      },
    ];
  }
  if (event.eventType === "PAYMENT_DUE") {
    return [{
      ...common,
      sourceExternalId: `${event.externalEventId}:payment`,
      title: event.title ?? "Kritikus pénzügyi mérföldkő",
      description: "Ellenőrizd a fizetési határidőt, a teljesítést és a kapcsolódó projektet.",
      priority: "P1",
      dueAt: event.dueAt ?? event.occurredAt,
      acceptanceCriteria: "A fizetendőség vagy blokkolás oka és a következő pénzügyi lépés rögzítve.",
      evidenceRequirement: { type: "APPROVAL", description: "Pénzügyesi ellenőrzés; utalás külön emberi jóváhagyással", machineVerifiable: false },
      sensitivity: "FINANCIAL",
    }];
  }
  if (event.eventType === "CHANGE_APPROVED") {
    return [{
      ...common,
      sourceExternalId: `${event.externalEventId}:change`,
      title: event.title ?? "Jóváhagyott változás átvezetése",
      description: "Vezesd át a változást az ütemterven, beszerzésen és pénzügyi előrejelzésen.",
      priority: "P1",
      dueAt: due,
      acceptanceCriteria: "Az idő-, költség- és dokumentumhatás ugyanahhoz a változásazonosítóhoz kapcsolódik.",
      evidenceRequirement: { type: "APPROVAL", description: "Ügyfél- és belső jóváhagyás pontos verzióval", machineVerifiable: false },
      sensitivity: "FINANCIAL",
    }];
  }
  return [{
    ...common,
    sourceExternalId: `${event.externalEventId}:quality-stop`,
    title: event.title ?? "Minőségellenőrzési STOP-pont",
    description: "A munkafázis blokkolt. Vizsgáld ki a hibát, jelöld ki a javítást és az újraellenőrzést.",
    priority: "P1",
    dueAt: event.occurredAt,
    acceptanceCriteria: "A blokkoló hiba javítva, újraellenőrizve és jogosult ember által lezárva.",
    evidenceRequirement: { type: "PHOTO", description: "Hiba- és javítási bizonyíték", machineVerifiable: false },
    sensitivity: "INTERNAL",
    status: "ASSIGNED",
  }];
}

export function explainDailyPriority(input: {
  priority: "P1" | "P2" | "P3" | "P4";
  dueAt: Date;
  reminderLevel: number;
  status: string;
}, now = new Date()) {
  const base = { P1: 400, P2: 300, P3: 200, P4: 100 }[input.priority];
  const overdueHours = Math.max(0, Math.floor((now.getTime() - input.dueAt.getTime()) / 3_600_000));
  const overdueScore = Math.min(160, overdueHours * 2);
  const reminderScore = Math.min(60, input.reminderLevel * 10);
  const blockedScore = input.status === "BLOCKED" ? 40 : 0;
  return {
    score: base + overdueScore + reminderScore + blockedScore,
    reasons: [
      `${input.priority} prioritás: ${base} pont`,
      ...(overdueHours ? [`${overdueHours} óra késés: +${overdueScore} pont`] : []),
      ...(reminderScore ? [`${input.reminderLevel}. emlékeztetési szint: +${reminderScore} pont`] : []),
      ...(blockedScore ? ["Blokkolt állapot: +40 pont"] : []),
    ],
  };
}

