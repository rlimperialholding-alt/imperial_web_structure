import type { Task } from "../domain/types.js";
import type { EscalationEvent } from "../domain/priority-policy.js";

export interface RenderedNotification {
  subject: string;
  text: string;
  html: string;
}

export function renderTaskReminder(
  task: Task,
  reminderLevel: number,
  escalation: EscalationEvent,
): RenderedNotification {
  const title =
    escalation === "P1_INCIDENT_REPORT"
      ? "Kritikus incidensjelentés"
      : escalation === "P1_ESCALATION"
        ? "Kritikus feladat eszkaláció"
        : reminderLevel === 1
          ? "Barátságos emlékeztető"
          : reminderLevel === 2
            ? "Határozott emlékeztető"
            : reminderLevel === 3
              ? "Sürgős: a feladat lejárt"
              : "Ismételt sürgős emlékeztető";

  const subjectPrefix =
    escalation === "P1_INCIDENT_REPORT"
      ? "[ITEP INCIDENT]"
      : escalation === "P1_ESCALATION"
        ? "[ITEP ESZKALÁCIÓ]"
        : reminderLevel >= 3
          ? "[ITEP LEJÁRT]"
          : "[ITEP EMLÉKEZTETŐ]";

  const lines = [
    title,
    "",
    `Feladat: ${task.title}`,
    `Azonosító: ${task.id}`,
    `Prioritás: ${task.priority}`,
    `Határidő: ${task.dueAt.toISOString()}`,
    `Aktuális státusz: ${task.status}`,
    `Elfogadási feltétel: ${task.acceptanceCriteria}`,
    `Elvárt bizonyíték: ${task.evidenceRequirement.description}`,
  ];

  if (task.blockedReason) {
    lines.push(`Blokkolás oka: ${task.blockedReason}`);
  }

  if (escalation !== "NONE") {
    lines.push(`Eszkaláció típusa: ${escalation}`);
  }

  lines.push(
    "",
    "A feladat csak ellenőrzött bizonyítékkal és elfogadással zárható le.",
  );

  const text = lines.join("\n");
  const html = `
    <main>
      <h1>${escapeHtml(title)}</h1>
      <p><strong>Feladat:</strong> ${escapeHtml(task.title)}</p>
      <p><strong>Azonosító:</strong> ${escapeHtml(task.id)}</p>
      <p><strong>Prioritás:</strong> ${escapeHtml(task.priority)}</p>
      <p><strong>Határidő:</strong> ${escapeHtml(task.dueAt.toISOString())}</p>
      <p><strong>Státusz:</strong> ${escapeHtml(task.status)}</p>
      <p><strong>Elfogadási feltétel:</strong> ${escapeHtml(task.acceptanceCriteria)}</p>
      <p><strong>Elvárt bizonyíték:</strong> ${escapeHtml(task.evidenceRequirement.description)}</p>
      ${task.blockedReason ? `<p><strong>Blokkolás oka:</strong> ${escapeHtml(task.blockedReason)}</p>` : ""}
      ${escalation !== "NONE" ? `<p><strong>Eszkaláció:</strong> ${escapeHtml(escalation)}</p>` : ""}
      <hr />
      <p>A feladat csak ellenőrzött bizonyítékkal és elfogadással zárható le.</p>
    </main>
  `.trim();

  return {
    subject: `${subjectPrefix} ${task.id} – ${task.title}`,
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
