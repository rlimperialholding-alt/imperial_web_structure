import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectChanges, projectEvents } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";
import { notificationAudience, queueProjectNotification } from "@/lib/notification-queue";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const { id } = await context.params;
    const body = await request.json() as { status?: "approved" | "rejected" };
    if (!body.status || !["approved", "rejected"].includes(body.status)) return Response.json({ error: "Érvénytelen döntés." }, { status: 400 });
    const db = await getDb();
    const now = new Date().toISOString();
    const [change] = await db.update(projectChanges).set({ status: body.status, customerDecisionAt: now, decidedByEmail: identity.email, updatedAt: now }).where(and(
      eq(projectChanges.id, id), eq(projectChanges.projectId, projectId), eq(projectChanges.status, "customer_approval"),
    )).returning();
    if (!change) return Response.json({ error: "A ChangeID nem található vagy még nem dönthető el." }, { status: 409 });
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: `change.${body.status}`, entityType: "change", entityId: id, detail: change.title, createdAt: now });
    await queueProjectNotification({
      projectId, actorEmail: identity.email, targetRoles: notificationAudience(membership.role), kind: "change",
      eventTitle: body.status === "approved" ? "ChangeID ügyféljóváhagyása rögzítve" : "ChangeID elutasítva",
      eventSummary: `${change.title} · ${id}`,
      relatedEntityType: "change", relatedEntityId: id, eventKey: `change-${id}-${body.status}`,
      portalUrl: `${new URL(request.url).origin}/myimperial`,
    }).catch(() => undefined);
    return Response.json({ change: { ...change, internalControl: "Belső kontroll teljesült" } });
  } catch (error) { return jsonError(error); }
}
