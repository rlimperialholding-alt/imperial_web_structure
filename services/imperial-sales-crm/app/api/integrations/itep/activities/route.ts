import { jsonError } from "@/lib/crm-auth";
import { listMigrationActivities } from "@/lib/migration-contract";
import { requireServiceToken } from "@/lib/service-auth";

export async function GET(request: Request) {
  try {
    await requireServiceToken(request, {
      environmentKey: "ITEP_CRM_READ_TOKEN",
      header: "X-ITEP-Token",
    });
    const url = new URL(request.url);
    const workspaceId = url.searchParams.get("workspace")?.trim() ?? "";
    const cursor = Number(url.searchParams.get("cursor") ?? "0");
    const limit = Math.min(100, Math.max(1, Number(url.searchParams.get("limit") ?? "50")));
    if (!workspaceId || !Number.isSafeInteger(cursor) || cursor < 0 || !Number.isSafeInteger(limit)) {
      return Response.json({ error: "Érvénytelen lapozási vagy workspace paraméter." }, {
        status: 400,
      });
    }
    return Response.json(await listMigrationActivities(workspaceId, cursor, limit));
  } catch (error) {
    return jsonError(error);
  }
}
