import { desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, contracts, customers } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function GET(request: Request) {
  try {
    await requireInternalCrmIdentity(request);
    const db = await getDb();
    const rows = await db.select({
      id: contracts.id,
      contractNumber: contracts.contractNumber,
      customerId: contracts.customerId,
      customerName: customers.name,
      leadId: contracts.leadId,
      projectId: contracts.projectId,
      title: contracts.title,
      contractType: contracts.contractType,
      netAmount: contracts.netAmount,
      vatRate: contracts.vatRate,
      grossAmount: contracts.grossAmount,
      currency: contracts.currency,
      status: contracts.status,
      effectiveDate: contracts.effectiveDate,
      signedAt: contracts.signedAt,
      sourceUrl: contracts.sourceUrl,
      createdAt: contracts.createdAt,
      updatedAt: contracts.updatedAt,
    }).from(contracts).innerJoin(customers, eq(customers.id, contracts.customerId))
      .orderBy(desc(contracts.updatedAt));
    return Response.json({ contracts: rows });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const body = await request.json() as Record<string, unknown>;
    const customerId = String(body.customerId ?? "").trim();
    const title = String(body.title ?? "").trim();
    const netAmount = Math.round(Number(body.netAmount ?? 0));
    const vatRate = Math.round(Number(body.vatRate ?? 27));
    const effectiveDate = String(body.effectiveDate ?? "").trim();
    const allowedTypes = ["construction", "design", "consulting", "other"] as const;
    const requestedType = String(body.contractType ?? "construction");
    const contractType = allowedTypes.includes(requestedType as typeof allowedTypes[number])
      ? requestedType as typeof allowedTypes[number]
      : "other";
    if (!customerId || !title || !effectiveDate || !Number.isSafeInteger(netAmount) || netAmount < 0 || vatRate < 0 || vatRate > 100) {
      return Response.json({ error: "Az ügyfél, megnevezés, hatálynap és érvényes összeg kötelező." }, { status: 400 });
    }
    const db = await getDb();
    const customer = (await db.select().from(customers)
      .where(eq(customers.id, customerId)).limit(1))[0];
    if (!customer || customer.status === "archived") {
      return Response.json({ error: "Aktív ügyfél nem található." }, { status: 404 });
    }
    const now = new Date().toISOString();
    const year = new Date().getUTCFullYear();
    const contract = {
      id: crypto.randomUUID(),
      contractNumber: String(body.contractNumber ?? "").trim()
        || `IH-${year}-${Date.now().toString(36).toUpperCase()}`,
      customerId,
      leadId: customer.sourceLeadId,
      projectId: null,
      title,
      contractType,
      netAmount,
      vatRate,
      grossAmount: Math.round(netAmount * (100 + vatRate) / 100),
      currency: String(body.currency ?? "HUF").trim().toUpperCase(),
      status: "draft" as const,
      effectiveDate,
      signedAt: null,
      sourceUrl: String(body.sourceUrl ?? "").trim() || null,
      createdByEmail: identity.email,
      createdAt: now,
      updatedAt: now,
    };
    await db.batch([
      db.insert(contracts).values(contract),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: "contract.created",
        entityType: "contract",
        entityId: contract.id,
        detail: `${contract.contractNumber} · ${customer.name} · ${contract.grossAmount} ${contract.currency}`,
        createdAt: now,
      }),
    ]);
    return Response.json({ contract: { ...contract, customerName: customer.name } }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
