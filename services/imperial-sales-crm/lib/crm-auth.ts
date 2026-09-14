import { and, inArray, eq } from "drizzle-orm";
import { projectMembers, users } from "@/db/schema";
import { getDb, getRuntimeValue } from "@/db";

export type CrmRole = "admin" | "sales_manager" | "sales";
export type CrmIdentity = { email: string; name: string; role: CrmRole };

function decodeHeader(value: string | null) {
  if (!value) return "";
  try { return decodeURIComponent(value); } catch { return value; }
}

export async function requireCrmIdentity(request: Request): Promise<CrmIdentity> {
  let email = decodeHeader(request.headers.get("oai-authenticated-user-email")).trim().toLowerCase();
  let name = decodeHeader(request.headers.get("oai-authenticated-user-name")).trim();

  if (!email && process.env.NODE_ENV !== "production") {
    email = "developer@terminal.local";
    name = "Helyi fejlesztő";
  }
  if (!email) throw new Response("Azonosítás szükséges.", { status: 401 });

  const adminEmail = (await getRuntimeValue("CRM_ADMIN_EMAIL"))?.trim().toLowerCase();
  const role: CrmRole = adminEmail && email === adminEmail ? "admin" : "sales";
  const identity = { email, name: name || email.split("@")[0], role };
  const db = await getDb();
  const now = new Date().toISOString();
  await db.insert(users).values({
    email, displayName: identity.name, role, createdAt: now, lastSeenAt: now,
  }).onConflictDoUpdate({
    target: users.email,
    set: { displayName: identity.name, role, lastSeenAt: now },
  });
  return identity;
}

export async function requireInternalCrmIdentity(request: Request): Promise<CrmIdentity> {
  const identity = await requireCrmIdentity(request);
  if (identity.role === "admin") return identity;
  const db = await getDb();
  const [customerMembership] = await db.select({ email: projectMembers.email }).from(projectMembers).where(and(
    inArray(projectMembers.role, ["customer", "contact"]),
    eq(projectMembers.email, identity.email),
  )).limit(1);
  if (customerMembership) throw new Response("A belső CRM csak Imperial munkatársak számára érhető el.", { status: 403 });
  return identity;
}

export function jsonError(error: unknown) {
  if (error instanceof Response) return error;
  console.error(error);
  return Response.json({ error: "A művelet most nem hajtható végre." }, { status: 500 });
}
