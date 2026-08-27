import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectEvents, projectInvitations } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    if (identity.role !== "admin" && membership.role !== "customer") return Response.json({ error: "Nincs jogosultságod a meghívás visszavonásához." }, { status: 403 });
    const { id } = await context.params;
    const now = new Date().toISOString();
    const db = await getDb();
    const [invitation] = await db.update(projectInvitations).set({ status: "revoked", updatedAt: now }).where(and(
      eq(projectInvitations.id, id), eq(projectInvitations.projectId, projectId), eq(projectInvitations.status, "pending"),
    )).returning();
    if (!invitation) return Response.json({ error: "Az aktív meghívás nem található." }, { status: 404 });
    await db.insert(projectEvents).values({ projectId, actorEmail: identity.email, action: "member.invitation_revoked", entityType: "invitation", entityId: id, detail: invitation.email, createdAt: now });
    return Response.json({ invitation: { ...invitation, tokenHash: undefined } });
  } catch (error) { return jsonError(error); }
}
