import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, cashflowEntries } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

const transitions = {
  planned: ["due", "paid", "cancelled"],
  due: ["paid", "cancelled"],
  paid: [],
  cancelled: [],
} as const;

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    if (identity.role !== "admin" && !identity.permissions.includes("*") && !identity.permissions.includes("finance.write")) {
      return Response.json({ error: "Nincs pénzügyi írási jogosultságod." }, { status: 403 });
    }
    const { id } = await context.params;
    const body = await request.json() as { status?: string; paidAt?: string };
    const db = await getDb();
    const entry = (await db.select().from(cashflowEntries).where(eq(cashflowEntries.id, id)).limit(1))[0];
    if (!entry) return Response.json({ error: "A cashflow-tétel nem található." }, { status: 404 });
    const status = String(body.status ?? "");
    if (!(transitions[entry.status] as readonly string[]).includes(status)) {
      return Response.json({ error: `A ${entry.status} állapotból ez az átmenet nem engedélyezett.` }, { status: 409 });
    }
    const now = new Date().toISOString();
    const nextStatus = status as "due" | "paid" | "cancelled";
    const paidAt = nextStatus === "paid" ? String(body.paidAt ?? now) : null;
    const [updated] = await db.update(cashflowEntries).set({ status: nextStatus, paidAt, updatedAt: now })
      .where(eq(cashflowEntries.id, id)).returning();
    await db.insert(businessAuditEvents).values({
      actorEmail: identity.email,
      action: `cashflow.${nextStatus}`,
      entityType: "cashflow_entry",
      entityId: id,
      detail: `${entry.amount} ${entry.currency} · ${entry.counterparty}`,
      createdAt: now,
    });
    return Response.json({ entry: updated });
  } catch (error) { return jsonError(error); }
}
