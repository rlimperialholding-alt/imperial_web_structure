import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { emailNotifications, notificationPreferences } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { getEmailProviderStatus } from "@/lib/email-delivery";
import { requireProjectAccess } from "@/lib/myimperial-auth";

const defaults = {
  taskNotifications: true,
  decisionNotifications: true,
  changeNotifications: true,
  documentNotifications: true,
  messageNotifications: true,
  careNotifications: true,
  digestFrequency: "immediate" as const,
};

const publicNotification = {
  id: emailNotifications.id,
  recipientEmail: emailNotifications.recipientEmail,
  recipientName: emailNotifications.recipientName,
  templateKey: emailNotifications.templateKey,
  subject: emailNotifications.subject,
  status: emailNotifications.status,
  approvalRequired: emailNotifications.approvalRequired,
  attemptCount: emailNotifications.attemptCount,
  lastError: emailNotifications.lastError,
  relatedEntityType: emailNotifications.relatedEntityType,
  relatedEntityId: emailNotifications.relatedEntityId,
  createdAt: emailNotifications.createdAt,
  sentAt: emailNotifications.sentAt,
};

export async function GET(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const db = await getDb();
    const now = new Date().toISOString();
    await db.insert(notificationPreferences).values({
      projectId, memberEmail: identity.email, ...defaults, updatedAt: now,
    }).onConflictDoNothing();
    const [preferences] = await db.select().from(notificationPreferences).where(and(
      eq(notificationPreferences.projectId, projectId), eq(notificationPreferences.memberEmail, identity.email),
    )).limit(1);
    const canApprove = identity.role === "admin" || membership.role === "customer";
    const notifications = canApprove
      ? await db.select(publicNotification).from(emailNotifications).where(eq(emailNotifications.projectId, projectId)).orderBy(desc(emailNotifications.createdAt)).limit(40)
      : await db.select(publicNotification).from(emailNotifications).where(and(eq(emailNotifications.projectId, projectId), eq(emailNotifications.recipientEmail, identity.email))).orderBy(desc(emailNotifications.createdAt)).limit(40);
    return Response.json({ preferences, notifications, canApprove, provider: await getEmailProviderStatus() });
  } catch (error) { return jsonError(error); }
}

export async function PATCH(request: Request) {
  try {
    const { identity, projectId } = await requireProjectAccess(request);
    const body = await request.json() as Partial<typeof defaults>;
    const booleanKeys = ["taskNotifications", "decisionNotifications", "changeNotifications", "documentNotifications", "messageNotifications", "careNotifications"] as const;
    if (booleanKeys.some((key) => key in body && typeof body[key] !== "boolean")) return Response.json({ error: "Érvénytelen értesítési beállítás." }, { status: 400 });
    if (body.digestFrequency && !["immediate", "daily", "weekly", "off"].includes(body.digestFrequency)) return Response.json({ error: "Érvénytelen összesítési gyakoriság." }, { status: 400 });
    const db = await getDb();
    const now = new Date().toISOString();
    const values = { projectId, memberEmail: identity.email, ...defaults, ...body, updatedAt: now };
    await db.insert(notificationPreferences).values(values).onConflictDoUpdate({
      target: [notificationPreferences.projectId, notificationPreferences.memberEmail],
      set: { ...body, updatedAt: now },
    });
    const [preferences] = await db.select().from(notificationPreferences).where(and(
      eq(notificationPreferences.projectId, projectId), eq(notificationPreferences.memberEmail, identity.email),
    )).limit(1);
    return Response.json({ preferences });
  } catch (error) { return jsonError(error); }
}
