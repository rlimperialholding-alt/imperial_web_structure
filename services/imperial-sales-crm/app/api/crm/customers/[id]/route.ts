import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, customers } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const { id } = await context.params;
    const body = await request.json() as Record<string, unknown>;
    const allowedStatus = ["prospect", "active", "archived"] as const;
    const status = String(body.status ?? "");
    if (status && !allowedStatus.includes(status as typeof allowedStatus[number])) {
      return Response.json({ error: "Érvénytelen ügyfélállapot." }, { status: 400 });
    }
    const changes = {
      ...(body.name !== undefined ? { name: String(body.name).trim() } : {}),
      ...(body.phone !== undefined ? { phone: String(body.phone).trim() } : {}),
      ...(body.billingAddress !== undefined ? { billingAddress: String(body.billingAddress).trim() } : {}),
      ...(status ? { status: status as typeof allowedStatus[number] } : {}),
      updatedAt: new Date().toISOString(),
    };
    const db = await getDb();
    const [customer] = await db.update(customers).set(changes)
      .where(eq(customers.id, id)).returning();
    if (!customer) return Response.json({ error: "Az ügyfél nem található." }, { status: 404 });
    await db.insert(businessAuditEvents).values({
      actorEmail: identity.email,
      action: "customer.updated",
      entityType: "customer",
      entityId: id,
      detail: Object.keys(changes).filter((key) => key !== "updatedAt").join(", "),
      createdAt: changes.updatedAt,
    });
    return Response.json({ customer });
  } catch (error) { return jsonError(error); }
}
