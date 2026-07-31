import { asc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import {
  businessAuditEvents,
  cashflowEntries,
  contractPaymentMilestones,
  contracts,
  customers,
} from "@/db/schema";
import { jsonError, requireInternalCrmIdentity, type CrmIdentity } from "@/lib/crm-auth";

function canWriteContracts(identity: CrmIdentity) {
  return identity.role === "admin" || identity.permissions.includes("*")
    || identity.permissions.includes("contract.write");
}

function validDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    await requireInternalCrmIdentity(request);
    const { id } = await context.params;
    const db = await getDb();
    const contract = (await db.select({ id: contracts.id }).from(contracts)
      .where(eq(contracts.id, id)).limit(1))[0];
    if (!contract) return Response.json({ error: "A szerződés nem található." }, { status: 404 });
    const milestones = await db.select().from(contractPaymentMilestones)
      .where(eq(contractPaymentMilestones.contractId, id))
      .orderBy(asc(contractPaymentMilestones.sequence));
    return Response.json({ milestones });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    if (!canWriteContracts(identity)) {
      return Response.json({ error: "Nincs szerződésírási jogosultságod." }, { status: 403 });
    }
    const { id } = await context.params;
    const body = await request.json() as Record<string, unknown>;
    const name = String(body.name ?? "").trim();
    const dueDate = String(body.dueDate ?? "").trim();
    const amount = Math.round(Number(body.amount ?? 0));
    if (!name || !validDate(dueDate) || !Number.isSafeInteger(amount) || amount <= 0) {
      return Response.json({ error: "A megnevezés, érvényes dátum és pozitív egész összeg kötelező." }, { status: 400 });
    }
    const db = await getDb();
    const row = (await db.select({ contract: contracts, customerName: customers.name })
      .from(contracts)
      .innerJoin(customers, eq(customers.id, contracts.customerId))
      .where(eq(contracts.id, id)).limit(1))[0];
    if (!row) return Response.json({ error: "A szerződés nem található." }, { status: 404 });
    if (!["draft", "review", "approved"].includes(row.contract.status)) {
      return Response.json({ error: "Aláírt vagy megszüntetett szerződés fizetési üteme nem módosítható." }, { status: 409 });
    }
    const current = await db.select().from(contractPaymentMilestones)
      .where(eq(contractPaymentMilestones.contractId, id));
    const scheduled = current
      .filter((milestone) => milestone.status !== "cancelled")
      .reduce((total, milestone) => total + milestone.amount, 0);
    if (scheduled + amount > row.contract.grossAmount) {
      return Response.json({
        error: `A fizetési ütem ${scheduled + amount - row.contract.grossAmount} ${row.contract.currency} összeggel meghaladná a szerződés bruttó értékét.`,
      }, { status: 409 });
    }
    const now = new Date().toISOString();
    const milestoneId = `PAY-${crypto.randomUUID().toUpperCase()}`;
    const cashflowEntryId = `CF-PAY-${crypto.randomUUID().toUpperCase()}`;
    const milestone = {
      id: milestoneId,
      contractId: id,
      sequence: current.reduce((maximum, item) => Math.max(maximum, item.sequence), 0) + 1,
      name,
      dueDate,
      amount,
      currency: row.contract.currency,
      status: "planned" as const,
      invoiceId: null,
      cashflowEntryId,
      createdByEmail: identity.email,
      createdAt: now,
      updatedAt: now,
    };
    await db.batch([
      db.insert(contractPaymentMilestones).values(milestone),
      db.insert(cashflowEntries).values({
        id: cashflowEntryId,
        sourceType: "contract_schedule",
        sourceId: milestoneId,
        direction: "inflow",
        category: "Szerződéses fizetési ütem",
        counterparty: row.customerName,
        description: `${row.contract.contractNumber} · ${name}`,
        projectId: row.contract.projectId,
        amount,
        currency: row.contract.currency,
        status: "planned",
        dueDate,
        paidAt: null,
        createdByEmail: identity.email,
        createdAt: now,
        updatedAt: now,
      }),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: "contract.payment_milestone.created",
        entityType: "contract_payment_milestone",
        entityId: milestoneId,
        detail: `${row.contract.contractNumber} · ${name} · ${amount} ${row.contract.currency}`,
        createdAt: now,
      }),
    ]);
    return Response.json({ milestone }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
