import { jsonError } from "@/lib/crm-auth";
import {
  importInvoices,
  listFinanceInvoices,
} from "@/lib/invoice-import";
import { requireServiceToken } from "@/lib/service-auth";

const tokenOptions = {
  environmentKey: "CRM_MIGRATION_TOKEN",
  header: "X-CRM-Migration-Token",
};

export async function POST(request: Request) {
  try {
    await requireServiceToken(request, tokenOptions);
    const result = await importInvoices(request);
    return Response.json(result, { status: result.newlyStored ? 201 : 200 });
  } catch (error) {
    return jsonError(error);
  }
}

export async function GET(request: Request) {
  try {
    await requireServiceToken(request, tokenOptions);
    const workspaceId = new URL(request.url).searchParams.get("workspace") ?? "";
    return Response.json({
      workspaceId,
      invoices: await listFinanceInvoices(workspaceId),
    });
  } catch (error) {
    return jsonError(error);
  }
}
