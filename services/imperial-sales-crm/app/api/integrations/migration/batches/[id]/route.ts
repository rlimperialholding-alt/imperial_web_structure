import { jsonError } from "@/lib/crm-auth";
import { getMigrationBatch } from "@/lib/migration-contract";
import { requireServiceToken } from "@/lib/service-auth";

export async function GET(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    await requireServiceToken(request, {
      environmentKey: "CRM_MIGRATION_TOKEN",
      header: "X-CRM-Migration-Token",
    });
    const { id } = await context.params;
    const result = await getMigrationBatch(id);
    if (!result) {
      return Response.json({ error: "A migrációs csomag nem található." }, {
        status: 404,
      });
    }
    return Response.json(result);
  } catch (error) {
    return jsonError(error);
  }
}
