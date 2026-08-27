import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { emailNotifications, projectEvents, projectInvitations, projects } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { deliverEmail, getEmailProviderStatus } from "@/lib/email-delivery";
import { invitationEmail } from "@/lib/email-templates";
import { invitationTokenHash } from "@/lib/invitation-token";
import { requireProjectAccess } from "@/lib/myimperial-auth";

export async function POST(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    if (identity.role !== "admin" && membership.role !== "customer") return Response.json({ error: "A meghívó jóváhagyásához nincs jogosultságod." }, { status: 403 });
    const body = await request.json() as { invitationId?: string; inviteUrl?: string };
    if (!body.invitationId || !body.inviteUrl) return Response.json({ error: "Hiányos meghívási adatok." }, { status: 400 });
    const inviteUrl = new URL(body.inviteUrl);
    if (inviteUrl.origin !== new URL(request.url).origin || inviteUrl.pathname !== "/myimperial/invite") return Response.json({ error: "Érvénytelen meghívási hivatkozás." }, { status: 400 });
    const token = inviteUrl.searchParams.get("token") || "";
    if (!token) return Response.json({ error: "A meghívási token hiányzik." }, { status: 400 });

    const db = await getDb();
    const [invitation] = await db.select().from(projectInvitations).where(and(
      eq(projectInvitations.id, body.invitationId), eq(projectInvitations.projectId, projectId), eq(projectInvitations.status, "pending"),
    )).limit(1);
    if (!invitation || invitation.expiresAt <= new Date().toISOString() || await invitationTokenHash(token) !== invitation.tokenHash) return Response.json({ error: "A meghívás lejárt vagy nem érvényes." }, { status: 409 });
    const [project] = await db.select().from(projects).where(eq(projects.id, projectId)).limit(1);
    if (!project) return Response.json({ error: "A projekt nem található." }, { status: 404 });
    const provider = await getEmailProviderStatus();
    if (!provider.configured) return Response.json({ error: "Az email-küldés még nincs konfigurálva. A linket továbbra is biztonságosan kimásolhatod.", provider }, { status: 409 });

    const template = invitationEmail({
      recipientName: invitation.displayName,
      projectTitle: project.title,
      portalCode: project.portalCode,
      inviteUrl: inviteUrl.toString(),
      expiresAt: invitation.expiresAt,
    });
    const key = `myimperial-invitation-${invitation.id}`;
    const now = new Date().toISOString();
    const [existing] = await db.select().from(emailNotifications).where(eq(emailNotifications.idempotencyKey, key)).limit(1);
    if (existing?.status === "sent") return Response.json({ notification: { id: existing.id, status: existing.status }, alreadySent: true });
    const notificationId = existing?.id || `EML-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
    if (existing) {
      await db.update(emailNotifications).set({
        subject: template.subject, htmlBody: template.html, textBody: template.text, status: "approved",
        approvedByEmail: identity.email, approvedAt: now, lastError: null, updatedAt: now,
      }).where(eq(emailNotifications.id, notificationId));
    } else {
      await db.insert(emailNotifications).values({
        id: notificationId, projectId, recipientEmail: invitation.email, recipientName: invitation.displayName,
        templateKey: "invitation", subject: template.subject, htmlBody: template.html, textBody: template.text,
        status: "approved", approvalRequired: true, approvedByEmail: identity.email, approvedAt: now,
        idempotencyKey: key, attemptCount: 0, relatedEntityType: "invitation", relatedEntityId: invitation.id,
        createdAt: now, updatedAt: now,
      });
    }
    await db.update(emailNotifications).set({ status: "sending", attemptCount: (existing?.attemptCount || 0) + 1, updatedAt: now }).where(eq(emailNotifications.id, notificationId));
    const result = await deliverEmail({ to: invitation.email, template, idempotencyKey: key });
    const finishedAt = new Date().toISOString();
    if (!result.ok) {
      await db.update(emailNotifications).set({ status: "failed", htmlBody: null, textBody: null, lastError: result.error, updatedAt: finishedAt }).where(eq(emailNotifications.id, notificationId));
      return Response.json({ error: result.error }, { status: 502 });
    }
    await db.update(emailNotifications).set({
      status: "sent", htmlBody: null, textBody: null, providerMessageId: result.messageId,
      sentAt: finishedAt, updatedAt: finishedAt,
    }).where(eq(emailNotifications.id, notificationId));
    await db.insert(projectEvents).values({
      projectId, actorEmail: identity.email, action: "invitation.email_sent", entityType: "invitation",
      entityId: invitation.id, detail: invitation.email, createdAt: finishedAt,
    });
    return Response.json({ notification: { id: notificationId, status: "sent" } });
  } catch (error) { return jsonError(error); }
}
