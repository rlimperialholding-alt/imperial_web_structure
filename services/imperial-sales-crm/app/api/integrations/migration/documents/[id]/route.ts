import { getDocumentBucket } from "@/db";
import { jsonError } from "@/lib/crm-auth";
import { getMigrationDocument } from "@/lib/migration-contract";
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
    const numericId = Number(id);
    if (!Number.isSafeInteger(numericId) || numericId < 1) {
      return Response.json({ error: "Érvénytelen dokumentumazonosító." }, {
        status: 400,
      });
    }
    const document = await getMigrationDocument(numericId);
    if (!document) {
      return Response.json({ error: "A migrált dokumentum nem található." }, {
        status: 404,
      });
    }
    const object = await (await getDocumentBucket()).get(document.objectKey);
    if (!object) {
      return Response.json({ error: "A migrált dokumentum tartalma nem található." }, {
        status: 404,
      });
    }
    return new Response(object.body, {
      headers: {
        "content-type": object.httpMetadata?.contentType || document.contentType,
        "content-length": String(object.size),
        "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(document.fileName)}`,
        "x-content-type-options": "nosniff",
        "cache-control": "private, no-store",
        "x-document-sha256": document.sha256,
      },
    });
  } catch (error) {
    return jsonError(error);
  }
}
