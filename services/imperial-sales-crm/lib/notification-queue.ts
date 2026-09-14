import { and, eq, inArray } from "drizzle-orm";
import { getDb } from "@/db";
import { emailNotifications, notificationPreferences, projectMembers, projects, users } from "@/db/schema";
import { projectEventEmail } from "@/lib/email-templates";

type ProjectRole = "customer" | "contact" | "project_manager" | "technical" | "finance" | "warranty";
type NotificationKind = "task" | "decision" | "change" | "document" | "message" | "care";

const preferenceField: Record<NotificationKind, keyof typeof notificationPreferences.$inferSelect> = {
  task: "taskNotifications",
  decision: "decisionNotifications",
  change: "changeNotifications",
  document: "documentNotifications",
  message: "messageNotifications",
  care: "careNotifications",
};

export function notificationAudience(actorRole: ProjectRole): ProjectRole[] {
  return actorRole === "customer" || actorRole === "contact"
    ? ["project_manager", "technical"]
    : ["customer", "contact"];
}

export async function queueProjectNotification(input: {
  projectId: string;
  actorEmail: string;
  targetRoles: ProjectRole[];
  kind: NotificationKind;
  eventTitle: string;
  eventSummary: string;
  relatedEntityType: string;
  relatedEntityId: string;
  eventKey: string;
  portalUrl: string;
}) {
  const db = await getDb();
  const [project] = await db.select().from(projects).where(eq(projects.id, input.projectId)).limit(1);
  if (!project) return 0;

  const members = await db.select({
    email: projectMembers.email,
    role: projectMembers.role,
    displayName: users.displayName,
  }).from(projectMembers).leftJoin(users, eq(projectMembers.email, users.email)).where(and(
    eq(projectMembers.projectId, input.projectId),
    inArray(projectMembers.role, input.targetRoles),
  ));
  const recipients = members.filter((member) => member.email !== input.actorEmail);
  if (!recipients.length) return 0;

  const preferences = await db.select().from(notificationPreferences).where(and(
    eq(notificationPreferences.projectId, input.projectId),
    inArray(notificationPreferences.memberEmail, recipients.map((member) => member.email)),
  ));
  const preferencesByEmail = new Map(preferences.map((item) => [item.memberEmail, item]));
  const now = new Date().toISOString();
  let queued = 0;

  for (const recipient of recipients) {
    const preference = preferencesByEmail.get(recipient.email);
    const field = preferenceField[input.kind];
    if (preference?.digestFrequency === "off" || preference?.[field] === false) continue;
    const recipientName = recipient.displayName || recipient.email.split("@")[0];
    const template = projectEventEmail({
      recipientName,
      projectTitle: project.title,
      portalCode: project.portalCode,
      eventTitle: input.eventTitle,
      eventSummary: input.eventSummary,
      portalUrl: input.portalUrl,
    });
    const id = `EML-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
    const inserted = await db.insert(emailNotifications).values({
      id,
      projectId: input.projectId,
      recipientEmail: recipient.email,
      recipientName,
      templateKey: input.kind,
      subject: template.subject,
      htmlBody: template.html,
      textBody: template.text,
      status: "draft",
      approvalRequired: true,
      idempotencyKey: `myimperial-${input.eventKey}-${recipient.email}`.slice(0, 256),
      attemptCount: 0,
      relatedEntityType: input.relatedEntityType,
      relatedEntityId: input.relatedEntityId,
      createdAt: now,
      updatedAt: now,
    }).onConflictDoNothing().returning({ id: emailNotifications.id });
    if (inserted.length) queued += 1;
  }
  return queued;
}
