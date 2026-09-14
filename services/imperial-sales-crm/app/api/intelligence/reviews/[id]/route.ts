import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { activities, importReviewItems } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity } from "@/lib/crm-auth";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    const { id: rawId } = await context.params;
    const id = Number(rawId);
    if (!Number.isSafeInteger(id) || id < 1) {
      return Response.json({ error: "Érvénytelen ellenőrzési azonosító." }, { status: 400 });
    }
    const body = await request.json() as { status?: unknown };
    if (body.status !== "resolved" && body.status !== "dismissed") {
      return Response.json({ error: "A státusz resolved vagy dismissed lehet." }, { status: 400 });
    }
    const workspaceId = process.env.CRM_WORKSPACE_ID ?? "imperial-live";
    const db = await getDb();
    const rows = await db.update(importReviewItems).set({
      status: body.status,
      resolvedAt: new Date().toISOString(),
    }).where(and(
      eq(importReviewItems.id, id),
      eq(importReviewItems.workspaceId, workspaceId),
      eq(importReviewItems.status, "open"),
    )).returning();
    if (!rows[0]) {
      return Response.json({ error: "A tétel nem található vagy már lezárt." }, { status: 404 });
    }
    await db.insert(activities).values({
      actorEmail: identity.email,
      action: body.status === "resolved" ? "IMPORT_REVIEW_RESOLVED" : "IMPORT_REVIEW_DISMISSED",
      entityType: "import_review",
      entityId: id,
      detail: rows[0].summary,
      createdAt: new Date().toISOString(),
    });
    return Response.json({ review: rows[0], resolvedBy: identity.email });
  } catch (error) {
    return jsonError(error);
  }
}
