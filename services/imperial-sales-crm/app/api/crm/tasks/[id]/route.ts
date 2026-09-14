import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import { activities, tasks } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const { id: rawId } = await context.params;
    const id = Number(rawId);
    const body = await request.json() as { done?: boolean };
    if (!Number.isInteger(id) || typeof body.done !== "boolean") return Response.json({ error:"Érvénytelen módosítás." }, { status:400 });
    const now = new Date().toISOString();
    const db = await getDb();
    const [task] = await db.update(tasks).set({ done:body.done, updatedAt:now }).where(eq(tasks.id,id)).returning();
    if (!task) return Response.json({ error:"A teendő nem található." }, { status:404 });
    await db.insert(activities).values({ actorEmail:identity.email, action:"task.completed", entityType:"task", entityId:id, detail:task.title, createdAt:now });
    return Response.json({ task });
  } catch (error) { return jsonError(error); }
}
