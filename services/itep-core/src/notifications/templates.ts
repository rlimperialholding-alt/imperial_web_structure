import type { Task } from "../domain/types.js";
import type { EscalationEvent } from "../domain/priority-policy.js";

export interface RenderedNotification {
  audience: "external" | "internal";
  subject: string;
  text: string;
  html: string;
}

export class NotificationTemplateError extends Error {}

const organizationBrandNames: Record<string, string> = {
  imperial: "Imperial Holding",
  "imperial-holding": "Imperial Holding",
  "imperial-intelligence": "Imperial Intelligence",
  "imperial-construction": "Imperial Construction",
  "imperial-knowledge": "Imperial Knowledge",
  "imperial-technologies": "Imperial Technologies",
  "imperial-venture-studio": "Imperial Venture Studio",
  property360: "Property 360",
  baushield: "BauShield",
  bautica: "Bautica",
  prefab: "Prefab",
  exitflow: "ExitFlow",
  veritas: "Veritas Construct",
  baufreund: "BauFreund",
  "danish-fabrik": "Danish Fabrik",
  timberhaus: "Timberhaus",
  "casa-moderna": "Casa Moderna",
  "everyday-homes": "Everyday Homes",
  "family-homes": "Family Homes",
  "budapesti-magasepito-vallalat": "Budapesti Magasépítő Vállalat",
  "red-property": "RED Property",
};

export function renderTaskReminder(
  task: Task,
  reminderLevel: number,
  escalation: EscalationEvent,
): RenderedNotification {
  const title =
    escalation === "P1_INCIDENT_REPORT"
      ? "Kritikus hiba"
      : escalation === "P1_ESCALATION"
        ? "Kritikus, lejárt feladat"
        : reminderLevel === 1
          ? "Barátságos emlékeztető"
          : reminderLevel === 2
            ? "Határozott emlékeztető"
            : reminderLevel === 3
              ? "Sürgős: a feladat lejárt"
              : "Ismételt sürgős emlékeztető";

  const brandName = organizationBrandNames[task.organizationId];
  if (!brandName) {
    throw new NotificationTemplateError(
      `Ismeretlen szervezeti márka: ${task.organizationId}`,
    );
  }
  // Task metadata is not proof that the actual mailbox is internal.  Treat the
  // message as external by default; the final sender may only relax this after
  // verifying every recipient domain.
  const audience = "external" as const;
  const subject = reminderLevel >= 3 || escalation !== "NONE"
    ? `Sürgős feladat – ${task.id}`
    : `Feladat emlékeztető – ${task.id}`;

  const lines = [
    `${title}.`,
    "",
    "Azért írunk, mert a következő feladat még nincs lezárva.",
    `Feladat: ${task.title}.`,
    `Határidő: ${task.dueAt.toISOString()}.`,
    `Teendő: ${task.acceptanceCriteria}.`,
    `Szükséges igazolás: ${task.evidenceRequirement.description}.`,
  ];

  if (task.blockedReason) {
    lines.push(`Az akadály oka: ${task.blockedReason}.`);
  }

  lines.push(
    "",
    "Ez segít Önnek, hogy a feladat időben lezárható legyen.",
    "Kérjük, végezze el a feladatot, majd küldje el a szükséges igazolást.",
    "",
    brandName,
  );

  const text = lines.join("\n");
  const html = `
    <main>
      <h1>${escapeHtml(title)}</h1>
      <p>Azért írunk, mert a következő feladat még nincs lezárva.</p>
      <p><strong>Feladat:</strong> ${escapeHtml(task.title)}</p>
      <p><strong>Határidő:</strong> ${escapeHtml(task.dueAt.toISOString())}</p>
      <p><strong>Teendő:</strong> ${escapeHtml(task.acceptanceCriteria)}</p>
      <p><strong>Szükséges igazolás:</strong> ${escapeHtml(task.evidenceRequirement.description)}</p>
      ${task.blockedReason ? `<p><strong>Az akadály oka:</strong> ${escapeHtml(task.blockedReason)}</p>` : ""}
      <p>Ez segít Önnek, hogy a feladat időben lezárható legyen.</p>
      <p>Kérjük, végezze el a feladatot, majd küldje el a szükséges igazolást.</p>
      <p>${escapeHtml(brandName)}</p>
    </main>
  `.trim();

  return {
    audience,
    subject,
    text,
    html,
  };
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
