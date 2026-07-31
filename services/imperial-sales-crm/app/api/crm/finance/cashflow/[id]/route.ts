import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, cashflowEntries, contractPaymentMilestones, contracts } from "@/db/schema";
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
    let linkedMilestone: typeof contractPaymentMilestones.$inferSelect | undefined;
    let linkedContractStatus: "draft" | "review" | "approved" | "signed" | "cancelled" | undefined;
    if (entry.sourceType === "contract_schedule" && entry.sourceId) {
      const linked = (await db.select({ milestone: contractPaymentMilestones, contractStatus: contracts.status })
        .from(contractPaymentMilestones)
        .innerJoin(contracts, eq(contracts.id, contractPaymentMilestones.contractId))
        .where(eq(contractPaymentMilestones.id, entry.sourceId)).limit(1))[0];
      linkedMilestone = linked?.milestone;
      linkedContractStatus = linked?.contractStatus;
      if (!linkedMilestone) return Response.json({ error: "A szerződéses cashflow forrása nem található." }, { status: 409 });
      if (entry.status === "planned" && nextStatus === "paid") {
        return Response.json({ error: "A szerződéses részletet fizetés előtt számlázottra kell állítani." }, { status: 409 });
      }
      if (nextStatus === "cancelled" && linkedContractStatus === "signed") {
        return Response.json({ error: "Aláírt szerződés fizetési részlete nem törölhető." }, { status: 409 });
      }
    }
    const results = await db.batch([
      db.update(cashflowEntries).set({ status: nextStatus, paidAt, updatedAt: now })
        .where(eq(cashflowEntries.id, id)).returning(),
      ...(linkedMilestone ? [db.update(contractPaymentMilestones).set({
        status: nextStatus === "due" ? "invoiced" : nextStatus,
        updatedAt: now,
      }).where(eq(contractPaymentMilestones.id, linkedMilestone.id))] : []),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: `cashflow.${nextStatus}`,
        entityType: "cashflow_entry",
        entityId: id,
        detail: `${entry.amount} ${entry.currency} · ${entry.counterparty}`,
        createdAt: now,
      }),
    ]);
    const [updated] = results[0];
    return Response.json({ entry: updated });
  } catch (error) { return jsonError(error); }
}
