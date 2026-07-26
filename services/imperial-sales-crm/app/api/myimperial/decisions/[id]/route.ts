import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectDecisions, projectEvents } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";
import { notificationAudience, queueProjectNotification } from "@/lib/notification-queue";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const { id: rawId } = await context.params;
    const id = Number(rawId);
    const body = await request.json() as { status?: "approved" | "question" };
    if (!Number.isInteger(id) || !body.status || !["approved", "question"].includes(body.status)) return Response.json({ error: "Érvénytelen döntés." }, { status: 400 });
    const db = await getDb();
    const now = new Date().toISOString();
    const [decision] = await db.update(projectDecisions).set({ status: body.status, response: body.status === "approved" ? "Jóváhagyva" : "Ügyfélkérdés érkezett", decidedAt: now, decidedByEmail: identity.email, updatedAt: now }).where(and(
      eq(projectDecisions.id, id), eq(projectDecisions.projectId, projectId), eq(projectDecisions.status, "open"),
    )).returning();
    if (!decision) return Response.json({ error: "A döntés nem található vagy már lezárult." }, { status: 409 });
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: `decision.${body.status}`, entityType: "decision", entityId: String(id), detail: decision.title, createdAt: now });
    await queueProjectNotification({
      projectId, actorEmail: identity.email, targetRoles: notificationAudience(membership.role), kind: "decision",
      eventTitle: body.status === "approved" ? "Projekt-döntés jóváhagyva" : "Kérdés érkezett egy döntéshez",
      eventSummary: `${decision.title} · Döntésazonosító: ${id}`,
      relatedEntityType: "decision", relatedEntityId: String(id), eventKey: `decision-${id}-${body.status}`,
      portalUrl: `${new URL(request.url).origin}/myimperial`,
    }).catch(() => undefined);
    return Response.json({ decision });
  } catch (error) { return jsonError(error); }
}
