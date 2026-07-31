import { asc, eq, or } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, customers, leads } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

function normalizeEmail(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

export async function GET(request: Request) {
  try {
    await requireInternalCrmIdentity(request);
    const db = await getDb();
    return Response.json({
      customers: await db.select().from(customers).orderBy(asc(customers.name)),
    });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const body = await request.json() as Record<string, unknown>;
    const leadId = Number(body.leadId ?? 0) || null;
    const db = await getDb();
    const lead = leadId
      ? (await db.select().from(leads).where(eq(leads.id, leadId)).limit(1))[0]
      : undefined;
    if (leadId && !lead) {
      return Response.json({ error: "Az értékesítési adatlap nem található." }, { status: 404 });
    }

    const name = String(body.name ?? lead?.name ?? "").trim();
    const email = normalizeEmail(body.email ?? lead?.email);
    const phone = String(body.phone ?? lead?.phone ?? "").trim();
    const billingAddress = String(body.billingAddress ?? "").trim();
    const customerType: "company" | "person" =
      body.customerType === "company" ? "company" : "person";
    if (!name || !email || !email.includes("@") || !phone || !billingAddress) {
      return Response.json(
        { error: "A név, érvényes e-mail, telefonszám és számlázási cím kötelező." },
        { status: 400 },
      );
    }
    const duplicate = (await db.select({ id: customers.id }).from(customers).where(
      leadId
        ? or(eq(customers.email, email), eq(customers.sourceLeadId, leadId))
        : eq(customers.email, email),
    ).limit(1))[0];
    if (duplicate) {
      return Response.json({ error: "Ehhez az e-mailhez vagy adatlaphoz már tartozik ügyfél." }, { status: 409 });
    }

    const now = new Date().toISOString();
    const customer = {
      id: crypto.randomUUID(),
      customerType,
      name,
      email,
      phone,
      billingAddress,
      taxNumber: String(body.taxNumber ?? "").trim() || null,
      companyRegistrationNumber: String(body.companyRegistrationNumber ?? "").trim() || null,
      sourceLeadId: leadId,
      status: "active" as const,
      createdByEmail: identity.email,
      createdAt: now,
      updatedAt: now,
    };
    await db.batch([
      db.insert(customers).values(customer),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: "customer.created",
        entityType: "customer",
        entityId: customer.id,
        detail: `${customer.name} · ${customer.email}`,
        createdAt: now,
      }),
    ]);
    return Response.json({ customer }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
