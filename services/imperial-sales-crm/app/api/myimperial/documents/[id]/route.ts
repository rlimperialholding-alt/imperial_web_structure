import { desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectDocuments, projectDocumentVersions } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { projectId } = await requireProjectAccess(request);
    const { id } = await context.params;
    const db = await getDb();
    const [document] = await db.select().from(projectDocuments).where(eq(projectDocuments.id, id)).limit(1);
    if (!document || document.projectId !== projectId) return Response.json({ error: "A dokumentum nem található." }, { status: 404 });
    const versions = await db.select({
      version: projectDocumentVersions.version,
      fileName: projectDocumentVersions.fileName,
      contentType: projectDocumentVersions.contentType,
      size: projectDocumentVersions.size,
      sha256: projectDocumentVersions.sha256,
      uploadedByEmail: projectDocumentVersions.uploadedByEmail,
      uploadedAt: projectDocumentVersions.uploadedAt,
    }).from(projectDocumentVersions).where(eq(projectDocumentVersions.documentId, id)).orderBy(desc(projectDocumentVersions.version));
    return Response.json({ document, versions });
  } catch (error) { return jsonError(error); }
}
