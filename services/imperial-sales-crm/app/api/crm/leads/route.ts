import { getDb } from "@/db";
import { activities, leads } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function POST(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const body = await request.json() as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    if (!name) return Response.json({ error: "A név megadása kötelező." }, { status: 400 });
    const now = new Date().toISOString();
    const db = await getDb();
    const [lead] = await db.insert(leads).values({
      name, title:String(body.title ?? "Új építési érdeklődés"), brand:String(body.brand ?? "Imperial"), brandCode:String(body.brandCode ?? "IH"),
      location:String(body.location ?? "Nincs megadva"), email:String(body.email ?? "—"), phone:String(body.phone ?? "—"), source:String(body.source ?? "Kézi rögzítés"),
      owner:String(body.owner ?? identity.name), ownerInitials:String(body.ownerInitials ?? identity.name.slice(0,2).toUpperCase()), stage:"new", value:0, probability:10,
      score:45, quality:38, temperature:"cold", health:"yellow", nextAction:"Első kapcsolatfelvétel", nextDate:"Ma", projectType:"Családi ház",
      technology:"Egyeztetendő", plot:false, financing:false, notes:"Újonnan rögzített adatlap; minősítés szükséges.", createdAt:now, updatedAt:now,
    }).returning();
    await db.insert(activities).values({ actorEmail:identity.email, action:"lead.created", entityType:"lead", entityId:lead.id, detail:`Új adatlap: ${lead.name}`, createdAt:now });
    return Response.json({ lead }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
