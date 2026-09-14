import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectEvents, projectTasks } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";
import { notificationAudience, queueProjectNotification } from "@/lib/notification-queue";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const { id } = await context.params;
    const body = await request.json() as { status?: "submitted" | "completed" };
    if (!body.status || !["submitted", "completed"].includes(body.status)) return Response.json({ error: "Érvénytelen teendőállapot." }, { status: 400 });
    const db = await getDb();
    const now = new Date().toISOString();
    const [task] = await db.update(projectTasks).set({ status: body.status, updatedAt: now }).where(and(
      eq(projectTasks.id, id), eq(projectTasks.projectId, projectId),
    )).returning();
    if (!task) return Response.json({ error: "A teendő nem található." }, { status: 404 });
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: `task.${body.status}`, entityType: "task", entityId: id, detail: task.title, createdAt: now });
    await queueProjectNotification({
      projectId, actorEmail: identity.email, targetRoles: notificationAudience(membership.role), kind: "task",
      eventTitle: body.status === "submitted" ? "Teendő teljesítésre beküldve" : "Teendő lezárva",
      eventSummary: `${task.title} · ${id}`,
      relatedEntityType: "task", relatedEntityId: id, eventKey: `task-${id}-${body.status}-${now}`,
      portalUrl: `${new URL(request.url).origin}/myimperial`,
    }).catch(() => undefined);
    return Response.json({ task });
  } catch (error) { return jsonError(error); }
}
