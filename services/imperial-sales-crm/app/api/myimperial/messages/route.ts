import { getDb } from "@/db";
import { projectEvents, projectMessages } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";
import { notificationAudience, queueProjectNotification } from "@/lib/notification-queue";

export async function POST(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const body = await request.json() as { topic?: string; body?: string };
    const topic = body.topic?.trim() || "Általános kérdés";
    const messageBody = body.body?.trim();
    if (!messageBody || messageBody.length > 5000) return Response.json({ error: "Az üzenet nem lehet üres." }, { status: 400 });
    const db = await getDb();
    const now = new Date().toISOString();
    const [message] = await db.insert(projectMessages).values({ projectId, authorEmail: identity.email, topic, body: messageBody, createdAt: now }).returning();
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: "message.created", entityType: "message", entityId: String(message.id), detail: topic, createdAt: now });
    await queueProjectNotification({
      projectId, actorEmail: identity.email, targetRoles: notificationAudience(membership.role), kind: "message",
      eventTitle: "Új dokumentált projektüzenet", eventSummary: topic,
      relatedEntityType: "message", relatedEntityId: String(message.id), eventKey: `message-${message.id}`,
      portalUrl: `${new URL(request.url).origin}/myimperial`,
    }).catch(() => undefined);
    return Response.json({ message }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
