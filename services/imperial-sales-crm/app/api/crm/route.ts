import { asc } from "drizzle-orm";
import { getDb } from "@/db";
import { leads, tasks } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";
import { seedCrmIfEmpty } from "@/lib/crm-seed";

export async function GET(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    await seedCrmIfEmpty(identity.email);
    const db = await getDb();
    const [leadRows, taskRows] = await Promise.all([
      db.select().from(leads).orderBy(asc(leads.id)),
      db.select().from(tasks).orderBy(asc(tasks.id)),
    ]);
    return Response.json({ identity, leads: leadRows, tasks: taskRows });
  } catch (error) { return jsonError(error); }
}
