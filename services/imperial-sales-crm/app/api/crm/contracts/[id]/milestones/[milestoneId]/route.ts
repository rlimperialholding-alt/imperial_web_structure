import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, cashflowEntries, contractPaymentMilestones, contracts } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity, type CrmIdentity } from "@/lib/crm-auth";

const transitions = {
  planned: ["invoiced", "cancelled"],
  invoiced: ["paid", "cancelled"],
  paid: [],
  cancelled: [],
} as const;

function canWriteContracts(identity: CrmIdentity) {
  return identity.role === "admin" || identity.permissions.includes("*")
    || identity.permissions.includes("contract.write") || identity.permissions.includes("finance.write");
}

export async function PATCH(request: Request, context: { params: Promise<{ id: string; milestoneId: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    if (!canWriteContracts(identity)) {
      return Response.json({ error: "Nincs jogosultságod a fizetési ütem módosításához." }, { status: 403 });
    }
    const { id, milestoneId } = await context.params;
    const body = await request.json() as Record<string, unknown>;
    const nextStatus = String(body.status ?? "") as "invoiced" | "paid" | "cancelled";
    const db = await getDb();
    const row = (await db.select({ milestone: contractPaymentMilestones, contractStatus: contracts.status })
      .from(contractPaymentMilestones)
      .innerJoin(contracts, eq(contracts.id, contractPaymentMilestones.contractId))
      .where(and(
        eq(contractPaymentMilestones.id, milestoneId),
        eq(contractPaymentMilestones.contractId, id),
      )).limit(1))[0];
    if (!row) return Response.json({ error: "A fizetési mérföldkő nem található." }, { status: 404 });
    if (!(transitions[row.milestone.status] as readonly string[]).includes(nextStatus)) {
      return Response.json({ error: `A ${row.milestone.status} állapotból ez az átmenet nem engedélyezett.` }, { status: 409 });
    }
    if (nextStatus === "cancelled" && row.contractStatus === "signed") {
      return Response.json({ error: "Aláírt szerződés fizetési mérföldköve nem törölhető." }, { status: 409 });
    }
    const now = new Date().toISOString();
    const cashflowStatus = nextStatus === "invoiced" ? "due" : nextStatus;
    await db.batch([
      db.update(contractPaymentMilestones).set({ status: nextStatus, updatedAt: now })
        .where(eq(contractPaymentMilestones.id, milestoneId)),
      db.update(cashflowEntries).set({
        status: cashflowStatus,
        paidAt: nextStatus === "paid" ? now : null,
        updatedAt: now,
      }).where(eq(cashflowEntries.id, row.milestone.cashflowEntryId)),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: `contract.payment_milestone.${nextStatus}`,
        entityType: "contract_payment_milestone",
        entityId: milestoneId,
        detail: `${row.milestone.name} · ${row.milestone.amount} ${row.milestone.currency}`,
        createdAt: now,
      }),
    ]);
    return Response.json({ milestone: { ...row.milestone, status: nextStatus, updatedAt: now } });
  } catch (error) { return jsonError(error); }
}
