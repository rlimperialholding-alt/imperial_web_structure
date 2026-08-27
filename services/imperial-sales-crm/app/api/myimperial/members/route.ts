import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectEvents, projectInvitations, projectMembers, users } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { createInvitationToken, invitationTokenHash } from "@/lib/invitation-token";
import { requireProjectAccess } from "@/lib/myimperial-auth";

const roles = ["customer", "contact", "project_manager", "technical", "finance", "warranty"] as const;
type ProjectRole = typeof roles[number];

function validEmail(value: string) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) && value.length <= 254;
}

export async function GET(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const db = await getDb();
    const [members, invitations] = await Promise.all([
      db.select({
        email: projectMembers.email,
        role: projectMembers.role,
        createdAt: projectMembers.createdAt,
        displayName: users.displayName,
      }).from(projectMembers).leftJoin(users, eq(projectMembers.email, users.email))
        .where(eq(projectMembers.projectId, projectId)),
      db.select({
        id: projectInvitations.id,
        email: projectInvitations.email,
        displayName: projectInvitations.displayName,
        role: projectInvitations.role,
        status: projectInvitations.status,
        expiresAt: projectInvitations.expiresAt,
        createdAt: projectInvitations.createdAt,
      }).from(projectInvitations).where(eq(projectInvitations.projectId, projectId))
        .orderBy(desc(projectInvitations.createdAt)),
    ]);
    return Response.json({
      members: members.map((member) => ({ ...member, displayName: member.displayName || member.email.split("@")[0] })),
      invitations,
      canManage: identity.role === "admin" || membership.role === "customer",
      allowedInviteRoles: identity.role === "admin" ? roles : ["contact"],
      platformAccess: "owner_only",
    });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const canManage = identity.role === "admin" || membership.role === "customer";
    if (!canManage) return Response.json({ error: "Nincs jogosultságod kapcsolattartót meghívni." }, { status: 403 });
    const body = await request.json() as { email?: string; displayName?: string; role?: ProjectRole };
    const email = body.email?.trim().toLowerCase() || "";
    const displayName = body.displayName?.trim() || "";
    const role = body.role;
    if (!validEmail(email) || !displayName || displayName.length > 120 || !role || !roles.includes(role)) return Response.json({ error: "Ellenőrizd a nevet, az email-címet és a szerepkört." }, { status: 400 });
    if (identity.role !== "admin" && role !== "contact") return Response.json({ error: "Ügyfélként csak további kapcsolattartót hívhatsz meg." }, { status: 403 });

    const db = await getDb();
    const [existingMember] = await db.select({ email: projectMembers.email }).from(projectMembers).where(and(
      eq(projectMembers.projectId, projectId), eq(projectMembers.email, email),
    )).limit(1);
    if (existingMember) return Response.json({ error: "Ez a személy már tagja a projektnek." }, { status: 409 });
    const [existingInvite] = await db.select({ id: projectInvitations.id }).from(projectInvitations).where(and(
      eq(projectInvitations.projectId, projectId), eq(projectInvitations.email, email), eq(projectInvitations.status, "pending"),
    )).limit(1);
    if (existingInvite) return Response.json({ error: "Erre az email-címre már van aktív meghívás." }, { status: 409 });

    const token = createInvitationToken();
    const tokenHash = await invitationTokenHash(token);
    const now = new Date();
    const expiresAt = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString();
    const id = `INV-${new Date().getFullYear()}-${crypto.randomUUID().slice(0, 6).toUpperCase()}`;
    const [invitation] = await db.insert(projectInvitations).values({
      id, projectId, email, displayName, role, tokenHash, status: "pending",
      invitedByEmail: identity.email, expiresAt, createdAt: now.toISOString(), updatedAt: now.toISOString(),
    }).returning();
    await db.insert(projectEvents).values({
      projectId, actorEmail: identity.email, action: "member.invited", entityType: "invitation",
      entityId: id, detail: `${displayName} · ${email} · ${role}`, createdAt: now.toISOString(),
    });
    const origin = new URL(request.url).origin;
    return Response.json({
      invitation: { id, email, displayName, role, status: invitation.status, expiresAt, createdAt: invitation.createdAt },
      inviteUrl: `${origin}/myimperial/invite?token=${token}`,
    }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
