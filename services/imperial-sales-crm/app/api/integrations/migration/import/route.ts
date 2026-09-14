import { jsonError } from "@/lib/crm-auth";
import { importMigrationBatch } from "@/lib/migration-contract";
import { requireServiceToken } from "@/lib/service-auth";

export async function POST(request: Request) {
  try {
    await requireServiceToken(request, {
      environmentKey: "CRM_MIGRATION_TOKEN",
      header: "X-CRM-Migration-Token",
    });
    const result = await importMigrationBatch(request);
    return Response.json(result, { status: result.newlyStored ? 201 : 200 });
  } catch (error) {
    return jsonError(error);
  }
}
