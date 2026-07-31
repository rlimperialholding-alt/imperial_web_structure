import { and, eq, inArray, ne } from "drizzle-orm";
import { getDb } from "@/db";
import {
  businessAuditEvents,
  cashflowEntries,
  contractPaymentMilestones,
  contracts,
  customers,
  leads,
  projectMembers,
  projects,
} from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

const transitions = {
  draft: ["review", "cancelled"],
  review: ["approved", "cancelled"],
  approved: ["signed", "cancelled"],
  signed: [],
  cancelled: [],
} as const;

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const { id } = await context.params;
    const body = await request.json() as Record<string, unknown>;
    const nextStatus = String(body.status ?? "");
    const db = await getDb();
    const contract = (await db.select().from(contracts)
      .where(eq(contracts.id, id)).limit(1))[0];
    if (!contract) return Response.json({ error: "A szerződés nem található." }, { status: 404 });
    if (!(transitions[contract.status] as readonly string[]).includes(nextStatus)) {
      return Response.json({ error: `A ${contract.status} állapotból ez az átmenet nem engedélyezett.` }, { status: 409 });
    }
    if (["approved", "signed"].includes(nextStatus) && identity.role === "sales") {
      return Response.json({ error: "Jóváhagyásra és aláírt állapotra csak vezető jogosult." }, { status: 403 });
    }
    const now = new Date().toISOString();

    if (nextStatus === "signed") {
      const targetCompletion = String(body.targetCompletion ?? "").trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(targetCompletion)) {
        return Response.json({ error: "A projekt érvényes tervezett befejezési dátuma kötelező." }, { status: 400 });
      }
      const milestones = await db.select().from(contractPaymentMilestones).where(and(
        eq(contractPaymentMilestones.contractId, contract.id),
        ne(contractPaymentMilestones.status, "cancelled"),
      ));
      const scheduledTotal = milestones.reduce((total, milestone) => total + milestone.amount, 0);
      if (milestones.length === 0 || scheduledTotal !== contract.grossAmount) {
        return Response.json({
          error: `Aláírás előtt a fizetési ütemnek pontosan le kell fednie a ${contract.grossAmount} ${contract.currency} bruttó értéket. Jelenleg: ${scheduledTotal} ${contract.currency}.`,
        }, { status: 409 });
      }
      const customer = (await db.select().from(customers)
        .where(eq(customers.id, contract.customerId)).limit(1))[0];
      if (!customer) return Response.json({ error: "A szerződés ügyfele nem található." }, { status: 409 });
      const projectId = `PRJ-${new Date().getUTCFullYear()}-${crypto.randomUUID().slice(0, 8).toUpperCase()}`;
      const portalCode = `MI-${new Date().getUTCFullYear()}-${crypto.randomUUID().slice(0, 6).toUpperCase()}`;
      const projectTitle = String(body.projectTitle ?? contract.title).trim();
      const project = {
        id: projectId,
        portalCode,
        customerName: customer.name,
        customerEmail: customer.email,
        customerId: customer.id,
        contractId: contract.id,
        title: projectTitle,
        status: "planning" as const,
        phase: "Projektindítás",
        progress: 0,
        targetCompletion,
        handoverDate: null,
        createdAt: now,
        updatedAt: now,
      };
      await db.batch([
        db.insert(projects).values(project),
        db.insert(projectMembers).values({
          projectId,
          email: customer.email,
          role: "customer",
          createdAt: now,
        }),
        db.update(contracts).set({ status: "signed", projectId, signedAt: now, updatedAt: now })
          .where(eq(contracts.id, contract.id)),
        db.update(cashflowEntries).set({ projectId, updatedAt: now }).where(inArray(
          cashflowEntries.id,
          milestones.map((milestone) => milestone.cashflowEntryId),
        )),
        ...(contract.leadId ? [
          db.update(leads).set({ stage: "contract", updatedAt: now })
            .where(eq(leads.id, contract.leadId)),
        ] : []),
        db.insert(businessAuditEvents).values({
          actorEmail: identity.email,
          action: "contract.signed_project.created",
          entityType: "contract",
          entityId: contract.id,
          detail: `${contract.contractNumber} · ${projectId} · ${portalCode}`,
          createdAt: now,
        }),
      ]);
      return Response.json({
        contract: { ...contract, status: "signed", projectId, signedAt: now, updatedAt: now },
        project,
      });
    }

    const status = nextStatus as "review" | "approved" | "cancelled";
    await db.batch([
      db.update(contracts).set({ status, updatedAt: now }).where(eq(contracts.id, id)),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: `contract.${status}`,
        entityType: "contract",
        entityId: id,
        detail: contract.contractNumber,
        createdAt: now,
      }),
    ]);
    return Response.json({ contract: { ...contract, status, updatedAt: now } });
  } catch (error) { return jsonError(error); }
}
