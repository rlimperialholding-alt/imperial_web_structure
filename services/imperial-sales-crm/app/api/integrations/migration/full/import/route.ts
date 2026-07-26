import { jsonError } from "@/lib/crm-auth";
import { importFullBatch } from "@/lib/full-import";
import { requireServiceToken } from "@/lib/service-auth";

export async function POST(request: Request) {
  try {
    await requireServiceToken(request, {
      environmentKey: "CRM_MIGRATION_TOKEN",
      header: "X-CRM-Migration-Token",
    });
    const result = await importFullBatch(request);
    const created = Object.values(result.newlyStored)
      .some((count) => count > 0);
    return Response.json(result, { status: created ? 201 : 200 });
  } catch (error) {
    return jsonError(error);
  }
}
