import { jsonError } from "@/lib/crm-auth";
import {
  importCustomers,
  listImportedCustomers,
} from "@/lib/customer-import";
import { requireServiceToken } from "@/lib/service-auth";

const tokenOptions = {
  environmentKey: "CRM_MIGRATION_TOKEN",
  header: "X-CRM-Migration-Token",
};

export async function POST(request: Request) {
  try {
    await requireServiceToken(request, tokenOptions);
    const result = await importCustomers(request);
    return Response.json(result, { status: result.newlyStored ? 201 : 200 });
  } catch (error) {
    return jsonError(error);
  }
}

export async function GET(request: Request) {
  try {
    await requireServiceToken(request, tokenOptions);
    const workspaceId = new URL(request.url).searchParams.get("workspace") ?? "";
    return Response.json(await listImportedCustomers(workspaceId));
  } catch (error) {
    return jsonError(error);
  }
}
