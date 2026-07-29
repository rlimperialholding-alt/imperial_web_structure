import { and, eq, inArray } from "drizzle-orm";
import { getDb } from "@/db";
import { projectMembers, users } from "@/db/schema";
import { verifyInternalUser } from "@/lib/itep-auth";

export type CrmRole = "admin" | "sales_manager" | "sales";
export type CrmIdentity = {
  email: string;
  name: string;
  role: CrmRole;
  organizationId: string;
  projectIds: string[];
  permissions: string[];
  isSystemAdmin: boolean;
  isExecutive: boolean;
};

export async function requireCrmIdentity(request: Request): Promise<CrmIdentity> {
  const user = await verifyInternalUser(request);
  const activeRole = user.activeRoles[0] ?? "";
  const role: CrmRole =
    user.isSystemAdmin || user.isExecutive || user.activePermissions.includes("*")
      ? "admin"
      : ["PROJECT_MANAGER", "SALES"].includes(activeRole)
        ? "sales_manager"
        : "sales";
  const identity: CrmIdentity = {
    email: user.email.trim().toLowerCase(),
    name: user.displayName,
    role,
    organizationId: user.activeOrganizationId,
    projectIds: user.activeProjectIds,
    permissions: user.activePermissions,
    isSystemAdmin: user.isSystemAdmin,
    isExecutive: user.isExecutive,
  };
  const db = await getDb();
  const now = new Date().toISOString();
  await db.insert(users).values({
    email: identity.email,
    displayName: identity.name,
    role,
    createdAt: now,
    lastSeenAt: now,
  }).onConflictDoUpdate({
    target: users.email,
    set: { displayName: identity.name, role, lastSeenAt: now },
  });
  return identity;
}

export async function requireInternalCrmIdentity(
  request: Request,
): Promise<CrmIdentity> {
  const identity = await requireCrmIdentity(request);
  if (identity.role === "admin") return identity;
  if (!identity.permissions.some((permission) =>
    ["customer.read", "customer.write", "customer.read.project"].includes(permission)
  )) {
    throw new Response("A belső CRM-hez nincs jogosultságod.", { status: 403 });
  }
  const db = await getDb();
  const [customerMembership] = await db
    .select({ email: projectMembers.email })
    .from(projectMembers)
    .where(and(
      inArray(projectMembers.role, ["customer", "contact"]),
      eq(projectMembers.email, identity.email),
    ))
    .limit(1);
  if (customerMembership) {
    throw new Response(
      "A belső CRM csak Imperial munkatársak számára érhető el.",
      { status: 403 },
    );
  }
  return identity;
}

export function jsonError(error: unknown) {
  if (error instanceof Response) return error;
  console.error(error);
  return Response.json(
    { error: "A művelet most nem hajtható végre." },
    { status: 500 },
  );
}
