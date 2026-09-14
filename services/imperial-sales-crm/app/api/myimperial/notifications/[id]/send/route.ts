import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { emailNotifications, projectEvents } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { deliverEmail, getEmailProviderStatus } from "@/lib/email-delivery";
import { requireProjectAccess } from "@/lib/myimperial-auth";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    if (identity.role !== "admin" && membership.role !== "customer") return Response.json({ error: "Az email jóváhagyásához nincs jogosultságod." }, { status: 403 });
    const provider = await getEmailProviderStatus();
    if (!provider.configured) return Response.json({ error: "Az email-küldés még nincs konfigurálva. A piszkozat megmaradt.", provider }, { status: 409 });
    const { id } = await context.params;
    const db = await getDb();
    const [notification] = await db.select().from(emailNotifications).where(and(
      eq(emailNotifications.id, id), eq(emailNotifications.projectId, projectId),
    )).limit(1);
    if (!notification) return Response.json({ error: "Az értesítés nem található." }, { status: 404 });
    if (notification.status === "sent") return Response.json({ notification: { ...notification, htmlBody: undefined, textBody: undefined }, alreadySent: true });
    if (!notification.htmlBody || !notification.textBody || !["draft", "failed"].includes(notification.status)) return Response.json({ error: "Ez az értesítés most nem küldhető." }, { status: 409 });

    const now = new Date().toISOString();
    await db.update(emailNotifications).set({
      status: "sending", approvedByEmail: identity.email, approvedAt: now,
      attemptCount: notification.attemptCount + 1, lastError: null, updatedAt: now,
    }).where(eq(emailNotifications.id, id));
    const result = await deliverEmail({
      to: notification.recipientEmail,
      idempotencyKey: notification.idempotencyKey,
      template: { subject: notification.subject, html: notification.htmlBody, text: notification.textBody },
    });
    const finishedAt = new Date().toISOString();
    if (!result.ok) {
      await db.update(emailNotifications).set({ status: "failed", lastError: result.error, updatedAt: finishedAt }).where(eq(emailNotifications.id, id));
      return Response.json({ error: result.error }, { status: 502 });
    }
    const [sent] = await db.update(emailNotifications).set({
      status: "sent", providerMessageId: result.messageId, sentAt: finishedAt, updatedAt: finishedAt,
    }).where(eq(emailNotifications.id, id)).returning();
    await db.insert(projectEvents).values({
      projectId, actorEmail: identity.email, action: "email.sent", entityType: "email_notification",
      entityId: id, detail: `${notification.templateKey} · ${notification.recipientEmail}`, createdAt: finishedAt,
    });
    return Response.json({ notification: { ...sent, htmlBody: undefined, textBody: undefined } });
  } catch (error) { return jsonError(error); }
}
