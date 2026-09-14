import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import { activities, leads } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

const validStages = new Set(["new", "contact", "consultation", "offer", "negotiation", "contract"]);
const validTemperatures = new Set(["hot", "warm", "cold"]);
const validHealth = new Set(["green", "yellow", "red"]);

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const { id: rawId } = await context.params;
    const id = Number(rawId);
    const body = await request.json() as Record<string, unknown>;
    if (!Number.isInteger(id)) return Response.json({ error:"Érvénytelen adatlap." }, { status:400 });
    const changes: Partial<typeof leads.$inferInsert> = {};
    const textFields = ["name", "title", "brand", "brandCode", "location", "email", "phone", "source", "owner", "ownerInitials", "nextAction", "nextDate", "projectType", "technology", "notes"] as const;
    for (const field of textFields) {
      if (typeof body[field] === "string") changes[field] = String(body[field]).trim().slice(0, field === "notes" ? 4000 : 300);
    }
    if (typeof body.stage === "string" && validStages.has(body.stage)) changes.stage = body.stage as typeof leads.$inferInsert.stage;
    if (typeof body.temperature === "string" && validTemperatures.has(body.temperature)) changes.temperature = body.temperature as typeof leads.$inferInsert.temperature;
    if (typeof body.health === "string" && validHealth.has(body.health)) changes.health = body.health as typeof leads.$inferInsert.health;
    for (const field of ["value", "probability", "score", "quality"] as const) {
      if (typeof body[field] === "number" && Number.isFinite(body[field])) changes[field] = Math.max(0, Math.round(body[field]));
    }
    if (typeof body.plot === "boolean") changes.plot = body.plot;
    if (typeof body.financing === "boolean") changes.financing = body.financing;
    if (!Object.keys(changes).length) return Response.json({ error:"Nincs menthető módosítás." }, { status:400 });
    if (changes.name === "") return Response.json({ error:"A név nem lehet üres." }, { status:400 });
    const now = new Date().toISOString();
    const db = await getDb();
    const [lead] = await db.update(leads).set({ ...changes, updatedAt:now }).where(eq(leads.id,id)).returning();
    if (!lead) return Response.json({ error:"Az adatlap nem található." }, { status:404 });
    const stageOnly = Object.keys(changes).length === 1 && changes.stage;
    await db.insert(activities).values({ actorEmail:identity.email, action:stageOnly?"lead.stage_changed":"lead.updated", entityType:"lead", entityId:id, detail:stageOnly?`Új státusz: ${changes.stage}`:"Adatlap adatai frissítve", createdAt:now });
    return Response.json({ lead });
  } catch (error) { return jsonError(error); }
}
