import { and, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectEvents, projectInvitations, projectMembers } from "@/db/schema";
import { jsonError, requireCrmIdentity } from "@/lib/crm-auth";
import { invitationTokenHash } from "@/lib/invitation-token";

export async function POST(request: Request) {
  try {
    const identity = await requireCrmIdentity(request);
    const body = await request.json() as { token?: string };
    const token = body.token?.trim() || "";
    if (token.length < 50) return Response.json({ error: "A meghívási hivatkozás érvénytelen." }, { status: 400 });
    const tokenHash = await invitationTokenHash(token);
    const db = await getDb();
    const [invitation] = await db.select().from(projectInvitations).where(and(
      eq(projectInvitations.tokenHash, tokenHash), eq(projectInvitations.status, "pending"),
    )).limit(1);
    if (!invitation) return Response.json({ error: "A meghívás nem található vagy már nem aktív." }, { status: 404 });
    const now = new Date();
    if (new Date(invitation.expiresAt) <= now) {
      await db.update(projectInvitations).set({ status: "expired", updatedAt: now.toISOString() }).where(eq(projectInvitations.id, invitation.id));
      return Response.json({ error: "A meghívás lejárt. Kérj új meghívót a projektgazdától." }, { status: 410 });
    }
    if (identity.email !== invitation.email) return Response.json({ error: `Ezt a meghívást a(z) ${invitation.email} címhez állították ki.` }, { status: 403 });
    await db.insert(projectMembers).values({
      projectId: invitation.projectId, email: identity.email, role: invitation.role, createdAt: now.toISOString(),
    }).onConflictDoNothing();
    await db.update(projectInvitations).set({ status: "accepted", acceptedAt: now.toISOString(), updatedAt: now.toISOString() }).where(eq(projectInvitations.id, invitation.id));
    await db.insert(projectEvents).values({ projectId: invitation.projectId, actorEmail: identity.email, action: "member.invitation_accepted", entityType: "member", entityId: identity.email, detail: invitation.role, createdAt: now.toISOString() });
    return Response.json({ accepted: true, projectId: invitation.projectId });
  } catch (error) { return jsonError(error); }
}
