import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectMembers } from "@/db/schema";
import { requireCrmIdentity } from "@/lib/crm-auth";
import { PILOT_PROJECT_ID, seedMyImperialIfEmpty } from "@/lib/myimperial-seed";

export async function requireProjectAccess(request: Request, projectId = PILOT_PROJECT_ID) {
  const identity = await requireCrmIdentity(request);
  await seedMyImperialIfEmpty(identity);
  const db = await getDb();
  const [membership] = await db.select().from(projectMembers).where(and(
    eq(projectMembers.projectId, projectId),
    eq(projectMembers.email, identity.email),
  )).limit(1);
  if (!membership) throw new Response("Ehhez a projekthez nincs hozzáférésed.", { status: 403 });
  return { identity, membership, projectId };
}

export function formatPortalDate(value: string) {
  return new Intl.DateTimeFormat("hu-HU", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "Europe/Budapest",
  }).format(new Date(value));
}
