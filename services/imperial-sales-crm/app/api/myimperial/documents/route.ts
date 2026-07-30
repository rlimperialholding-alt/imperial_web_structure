import { desc, eq, inArray, sql } from "drizzle-orm";
import { getDb, getDocumentBucket } from "@/db";
import { projectDocuments, projectDocumentVersions, projectEvents } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import {
  assertProjectDocumentQuota,
  sha256Hex,
  safeFileName,
  validateDocumentFile,
} from "@/lib/document-upload";
import { requireProjectAccess } from "@/lib/myimperial-auth";
import { notificationAudience, queueProjectNotification } from "@/lib/notification-queue";

const documentGroups = ["Szerződések", "Tervezés", "Telek", "Pénzügy", "Jegyzőkönyvek", "Egyéb"];

export async function GET(request: Request) {
  try {
    const { projectId } = await requireProjectAccess(request);
    const db = await getDb();
    const docs = await db.select().from(projectDocuments).where(eq(projectDocuments.projectId, projectId)).orderBy(desc(projectDocuments.updatedAt));
    if (!docs.length) return Response.json({ documents: [] });
    const versions = await db.select().from(projectDocumentVersions)
      .where(inArray(projectDocumentVersions.documentId, docs.map((document) => document.id)))
      .orderBy(desc(projectDocumentVersions.uploadedAt));
    return Response.json({ documents: docs.map((document) => {
      const current = versions.find((version) => version.documentId === document.id && version.version === document.currentVersion);
      return {
        ...document,
        fileName: current?.fileName || "",
        contentType: current?.contentType || "",
        size: current?.size || 0,
        sha256: current?.sha256 || "",
        uploadedAt: current?.uploadedAt || document.updatedAt,
        uploadedByEmail: current?.uploadedByEmail || "",
        downloadUrl: `/api/myimperial/documents/${document.id}/download`,
      };
    }) });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request) {
  let objectKey = "";
  let newDocumentId = "";
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) return Response.json({ error: "Válassz feltöltendő fájlt." }, { status: 400 });
    const requestedDocumentId = String(form.get("documentId") || "").trim();
    const requestedName = String(form.get("name") || "").trim();
    const requestedGroup = String(form.get("group") || "Egyéb").trim();
    if (!documentGroups.includes(requestedGroup)) return Response.json({ error: "Érvénytelen dokumentumcsoport." }, { status: 400 });
    if (!requestedDocumentId && (!requestedName || requestedName.length > 140)) return Response.json({ error: "Add meg a dokumentum nevét." }, { status: 400 });

    const data = await validateDocumentFile(file);
    const sha256 = await sha256Hex(data);
    const db = await getDb();
    const [storageUsage] = await db
      .select({
        usedBytes: sql<number>`coalesce(sum(${projectDocumentVersions.size}), 0)`,
      })
      .from(projectDocumentVersions)
      .innerJoin(
        projectDocuments,
        eq(projectDocuments.id, projectDocumentVersions.documentId),
      )
      .where(eq(projectDocuments.projectId, projectId));
    assertProjectDocumentQuota(Number(storageUsage?.usedBytes || 0), file.size);
    const now = new Date().toISOString();
    let document: typeof projectDocuments.$inferSelect | undefined;
    if (requestedDocumentId) {
      [document] = await db.select().from(projectDocuments).where(eq(projectDocuments.id, requestedDocumentId)).limit(1);
      if (!document || document.projectId !== projectId) return Response.json({ error: "A dokumentum nem található." }, { status: 404 });
    }

    const documentId = document?.id || `DOC-${new Date().getFullYear()}-${crypto.randomUUID().slice(0, 6).toUpperCase()}`;
    const version = (document?.currentVersion || 0) + 1;
    const fileName = safeFileName(file.name);
    objectKey = `${projectId}/${documentId}/v${version}/${crypto.randomUUID()}`;
    const bucket = await getDocumentBucket();
    await bucket.put(objectKey, data, {
      httpMetadata: { contentType: file.type },
      customMetadata: { projectId, documentId, version: String(version), sha256, fileName },
    });

    if (!document) {
      newDocumentId = documentId;
      [document] = await db.insert(projectDocuments).values({
        id: documentId, projectId, name: requestedName, group: requestedGroup,
        status: "approval", currentVersion: version, createdAt: now, updatedAt: now,
      }).returning();
    }
    await db.insert(projectDocumentVersions).values({
      documentId, version, objectKey, fileName, contentType: file.type, size: file.size,
      sha256, uploadedByEmail: identity.email, uploadedAt: now,
    });
    if (version > 1) await db.update(projectDocuments).set({ currentVersion: version, status: "approval", updatedAt: now }).where(eq(projectDocuments.id, documentId));
    await db.insert(projectEvents).values({
      projectId, actorEmail: identity.email, action: "document.uploaded", entityType: "document",
      entityId: documentId, detail: `${document.name} · v${version} · SHA-256 ${sha256}`, createdAt: now,
    });
    await queueProjectNotification({
      projectId, actorEmail: identity.email, targetRoles: notificationAudience(membership.role), kind: "document",
      eventTitle: "Új projekt-dokumentum érkezett", eventSummary: `${document.name} · v${version}`,
      relatedEntityType: "document", relatedEntityId: documentId, eventKey: `document-${documentId}-v${version}`,
      portalUrl: `${new URL(request.url).origin}/myimperial`,
    }).catch(() => undefined);
    return Response.json({ document: {
      ...document, currentVersion: version, status: "approval", updatedAt: now,
      fileName, contentType: file.type, size: file.size, sha256, uploadedAt: now,
      uploadedByEmail: identity.email, downloadUrl: `/api/myimperial/documents/${documentId}/download`,
    } }, { status: 201 });
  } catch (error) {
    if (objectKey) {
      try { await (await getDocumentBucket()).delete(objectKey); } catch { /* best-effort orphan cleanup */ }
    }
    if (newDocumentId) {
      try { await (await getDb()).delete(projectDocuments).where(eq(projectDocuments.id, newDocumentId)); } catch { /* best-effort metadata cleanup */ }
    }
    return jsonError(error);
  }
}
