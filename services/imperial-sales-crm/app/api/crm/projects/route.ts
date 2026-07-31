import { desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { contracts, customers, projects } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function GET(request: Request) {
  try {
    await requireInternalCrmIdentity(request);
    const db = await getDb();
    const rows = await db.select({
      id: projects.id,
      portalCode: projects.portalCode,
      title: projects.title,
      customerId: projects.customerId,
      customerName: customers.name,
      contractId: projects.contractId,
      contractNumber: contracts.contractNumber,
      status: projects.status,
      phase: projects.phase,
      progress: projects.progress,
      targetCompletion: projects.targetCompletion,
      updatedAt: projects.updatedAt,
    }).from(projects)
      .leftJoin(customers, eq(customers.id, projects.customerId))
      .leftJoin(contracts, eq(contracts.id, projects.contractId))
      .orderBy(desc(projects.updatedAt));
    return Response.json({ projects: rows });
  } catch (error) { return jsonError(error); }
}
