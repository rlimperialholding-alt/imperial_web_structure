import { and, eq } from "drizzle-orm";
import { getDb, getDocumentBucket } from "@/db";
import { projectDocuments, projectDocumentVersions, projectEvents } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { identity, projectId } = await requireProjectAccess(request);
    const { id } = await context.params;
    const requestedVersion = Number(new URL(request.url).searchParams.get("version"));
    const db = await getDb();
    const [document] = await db.select().from(projectDocuments).where(and(eq(projectDocuments.id, id), eq(projectDocuments.projectId, projectId))).limit(1);
    if (!document) return Response.json({ error: "A dokumentum nem található." }, { status: 404 });
    const versionNumber = Number.isInteger(requestedVersion) && requestedVersion > 0 ? requestedVersion : document.currentVersion;
    const [version] = await db.select().from(projectDocumentVersions).where(and(
      eq(projectDocumentVersions.documentId, id), eq(projectDocumentVersions.version, versionNumber),
    )).limit(1);
    if (!version) return Response.json({ error: "A dokumentumverzió nem található." }, { status: 404 });
    const object = await (await getDocumentBucket()).get(version.objectKey);
    if (!object) return Response.json({ error: "A dokumentum tartalma nem található." }, { status: 404 });
    const now = new Date().toISOString();
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: "document.downloaded", entityType: "document", entityId: id, detail: `${document.name} · v${versionNumber}`, createdAt: now });
    const fallback = version.fileName.replace(/[^a-zA-Z0-9._-]/g, "_");
    return new Response(object.body, { headers: {
      "content-type": object.httpMetadata?.contentType || version.contentType,
      "content-length": String(object.size),
      "content-disposition": `attachment; filename="${fallback}"; filename*=UTF-8''${encodeURIComponent(version.fileName)}`,
      "x-content-type-options": "nosniff",
      "cache-control": "private, no-store",
      "x-document-sha256": version.sha256,
    } });
  } catch (error) { return jsonError(error); }
}
