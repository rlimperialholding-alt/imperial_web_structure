import { asc } from "drizzle-orm";
import { getDb } from "@/db";
import { contractPaymentMilestones, contracts, customers, leads, projects, tasks } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";
import { seedCrmIfEmpty } from "@/lib/crm-seed";
import { getFullImportStatus } from "@/lib/full-import";
import { listFinanceInvoices } from "@/lib/invoice-import";

export async function GET(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    await seedCrmIfEmpty(identity.email);
    const db = await getDb();
    const [leadRows, taskRows, customerRows, contractRows, milestoneRows, projectRows, invoiceRows, importStatus] = await Promise.all([
      db.select().from(leads).orderBy(asc(leads.id)),
      db.select().from(tasks).orderBy(asc(tasks.id)),
      db.select().from(customers).orderBy(asc(customers.name)),
      db.select().from(contracts).orderBy(asc(contracts.contractNumber)),
      db.select().from(contractPaymentMilestones).orderBy(asc(contractPaymentMilestones.sequence)),
      db.select().from(projects).orderBy(asc(projects.portalCode)),
      listFinanceInvoices(),
      getFullImportStatus(process.env.CRM_WORKSPACE_ID ?? "imperial-live"),
    ]);
    return Response.json({
      identity,
      leads: leadRows,
      tasks: taskRows,
      customers: customerRows,
      contracts: contractRows,
      contractMilestones: milestoneRows,
      projects: projectRows,
      invoices: invoiceRows,
      importStatus,
    });
  } catch (error) { return jsonError(error); }
}
