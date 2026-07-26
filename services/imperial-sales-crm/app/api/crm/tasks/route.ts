import { getDb } from "@/db";
import { activities, leads, tasks } from "@/db/schema";
import { eq } from "drizzle-orm";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

const priorities = new Set(["critical", "high", "normal"]);

export async function POST(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const body = await request.json() as Record<string, unknown>;
    const leadId = Number(body.leadId);
    const title = String(body.title ?? "").trim();
    if (!Number.isInteger(leadId) || !title) return Response.json({ error:"A teendő címe és adatlapja kötelező." }, { status:400 });
    const db = await getDb();
    const [lead] = await db.select({ id:leads.id, name:leads.name }).from(leads).where(eq(leads.id,leadId)).limit(1);
    if (!lead) return Response.json({ error:"Az adatlap nem található." }, { status:404 });
    const priority = priorities.has(String(body.priority)) ? String(body.priority) as typeof tasks.$inferInsert.priority : "normal";
    const now = new Date().toISOString();
    const [task] = await db.insert(tasks).values({
      title:title.slice(0,300), leadId, leadName:lead.name, type:String(body.type??"Teendő").slice(0,80), due:String(body.due??"Ma").slice(0,100),
      priority, done:false, ai:false, ownerEmail:identity.email, createdAt:now, updatedAt:now,
    }).returning();
    await db.insert(activities).values({ actorEmail:identity.email, action:"task.created", entityType:"lead", entityId:leadId, detail:`Új teendő: ${task.title}`, createdAt:now });
    return Response.json({ task }, { status:201 });
  } catch (error) { return jsonError(error); }
}
