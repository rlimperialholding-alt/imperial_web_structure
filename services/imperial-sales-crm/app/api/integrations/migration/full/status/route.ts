import { jsonError } from "@/lib/crm-auth";
import { getFullImportStatus } from "@/lib/full-import";
import { requireServiceToken } from "@/lib/service-auth";

export async function GET(request: Request) {
  try {
    await requireServiceToken(request, {
      environmentKey: "ITEP_CRM_READ_TOKEN",
      header: "X-ITEP-CRM-Token",
    });
    const url = new URL(request.url);
    const result = await getFullImportStatus(
      url.searchParams.get("workspaceId") ?? "",
    );
    return Response.json(result);
  } catch (error) {
    return jsonError(error);
  }
}
