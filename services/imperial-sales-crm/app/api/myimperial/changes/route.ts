import { desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectChanges, projectEvents } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";
import { notificationAudience, queueProjectNotification } from "@/lib/notification-queue";

export async function POST(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const body = await request.json() as { title?: string; description?: string; category?: string };
    const title = body.title?.trim();
    const scope = body.description?.trim();
    if (!title || !scope || title.length > 140 || scope.length > 3000) return Response.json({ error: "A megnevezés és a leírás kitöltése szükséges." }, { status: 400 });
    const db = await getDb();
    const [latest] = await db.select({ id: projectChanges.id }).from(projectChanges).where(eq(projectChanges.projectId, projectId)).orderBy(desc(projectChanges.createdAt)).limit(1);
    const nextNumber = Math.max(5, Number(latest?.id.match(/(\d+)$/)?.[1] ?? 4) + 1);
    const id = `CHG-${new Date().getFullYear()}-${String(nextNumber).padStart(3, "0")}`;
    const now = new Date().toISOString();
    const [change] = await db.insert(projectChanges).values({
      id, projectId, title, origin: `Ügyféligény${body.category ? ` · ${body.category}` : ""}`, scope,
      customerPriceImpact: "Elemzés alatt", scheduleImpact: "Elemzés alatt", internalControlStatus: "pending",
      status: "internal_review", evidence: "Hatáselemzés készül", createdAt: now, updatedAt: now,
    }).returning();
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: "change.created", entityType: "change", entityId: id, detail: title, createdAt: now });
    await queueProjectNotification({
      projectId, actorEmail: identity.email, targetRoles: notificationAudience(membership.role), kind: "change",
      eventTitle: "Új ChangeID került rögzítésre", eventSummary: `${title} · ${id}`,
      relatedEntityType: "change", relatedEntityId: id, eventKey: `change-${id}-created`,
      portalUrl: `${new URL(request.url).origin}/myimperial`,
    }).catch(() => undefined);
    return Response.json({ change: { ...change, internalControl: "Ellenőrzés alatt" } }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
