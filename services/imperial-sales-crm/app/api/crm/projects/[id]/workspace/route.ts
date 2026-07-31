import { and, asc, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import {
  businessAuditEvents,
  projectComments,
  projectDocuments,
  projectEvents,
  projectMembers,
  projectMessages,
  projects,
  projectTasks,
} from "@/db/schema";
import { jsonError, requireInternalCrmIdentity, type CrmIdentity } from "@/lib/crm-auth";

type InternalProjectRole = "project_manager" | "technical" | "finance" | "warranty";

function hasProjectPermission(identity: CrmIdentity, write = false) {
  return identity.role === "admin" || identity.permissions.includes("*")
    || identity.permissions.includes(write ? "project.write" : "project.read");
}

async function authorizeProject(request: Request, id: string, write = false) {
  const identity = await requireInternalCrmIdentity(request);
  const db = await getDb();
  const project = (await db.select().from(projects).where(eq(projects.id, id)).limit(1))[0];
  if (!project) throw new Response("A projekt nem található.", { status: 404 });
  const membership = (await db.select().from(projectMembers).where(and(
    eq(projectMembers.projectId, id),
    eq(projectMembers.email, identity.email),
  )).limit(1))[0];
  const staffMember = membership && !["customer", "contact"].includes(membership.role);
  const memberAccess = staffMember && (!write || membership.role === "project_manager");
  if (!hasProjectPermission(identity, write) && !memberAccess) {
    throw new Response("Ehhez a projekthez nincs jogosultságod.", { status: 403 });
  }
  return { identity, db, project, membership };
}

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    const { identity, db, project, membership } = await authorizeProject(request, id);
    const [tasks, comments, messages, documents, members, events] = await Promise.all([
      db.select().from(projectTasks).where(eq(projectTasks.projectId, id)).orderBy(asc(projectTasks.due)),
      db.select().from(projectComments).where(eq(projectComments.projectId, id)).orderBy(desc(projectComments.createdAt)),
      db.select().from(projectMessages).where(eq(projectMessages.projectId, id)).orderBy(desc(projectMessages.createdAt)),
      db.select().from(projectDocuments).where(eq(projectDocuments.projectId, id)).orderBy(desc(projectDocuments.updatedAt)),
      db.select().from(projectMembers).where(eq(projectMembers.projectId, id)).orderBy(asc(projectMembers.role)),
      db.select().from(projectEvents).where(eq(projectEvents.projectId, id)).orderBy(desc(projectEvents.createdAt)).limit(100),
    ]);
    return Response.json({ identity, membership, project, tasks, comments, messages, documents, members, events });
  } catch (error) { return jsonError(error); }
}

export async function PATCH(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    const { identity, db, project, membership } = await authorizeProject(request, id);
    const body = await request.json() as Record<string, unknown>;
    if (body.action === "task_status") {
      const taskId = String(body.taskId ?? "");
      const status = String(body.status ?? "") as "submitted" | "completed";
      const task = (await db.select().from(projectTasks).where(and(
        eq(projectTasks.id, taskId), eq(projectTasks.projectId, id),
      )).limit(1))[0];
      if (!task) return Response.json({ error: "A projektfeladat nem található." }, { status: 404 });
      const canClose = hasProjectPermission(identity, true) || membership?.role === "project_manager"
        || task.assignedToEmail === identity.email;
      if (!canClose) return Response.json({ error: "Csak a felelős vagy a projektmenedzser zárhatja le a feladatot." }, { status: 403 });
      if (!["submitted", "completed"].includes(status)) return Response.json({ error: "Érvénytelen feladatállapot." }, { status: 400 });
      const now = new Date().toISOString();
      const [updatedTask] = await db.update(projectTasks).set({ status, updatedAt: now })
        .where(eq(projectTasks.id, taskId)).returning();
      await db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: `task.${status}`, entityType: "task", entityId: taskId, detail: task.title, createdAt: now });
      return Response.json({ task: updatedTask });
    }
    if (!hasProjectPermission(identity, true) && membership?.role !== "project_manager") {
      return Response.json({ error: "A projekt állapotát csak a projektmenedzser módosíthatja." }, { status: 403 });
    }
    const progress = Math.round(Number(body.progress ?? project.progress));
    const phase = String(body.phase ?? project.phase).trim();
    const targetCompletion = String(body.targetCompletion ?? project.targetCompletion).trim();
    const status = String(body.status ?? project.status) as typeof project.status;
    if (!Number.isSafeInteger(progress) || progress < 0 || progress > 100 || !phase || !/^\d{4}-\d{2}-\d{2}$/.test(targetCompletion)
      || !["planning", "construction", "handover", "care"].includes(status)) {
      return Response.json({ error: "A fázis, 0–100% készültség, állapot és érvényes céldátum kötelező." }, { status: 400 });
    }
    const now = new Date().toISOString();
    const [updated] = await db.update(projects).set({ phase, progress, status, targetCompletion, updatedAt: now })
      .where(eq(projects.id, id)).returning();
    await db.batch([
      db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "project.progress.updated", entityType: "project", entityId: id, detail: `${phase} · ${progress}% · ${targetCompletion}`, createdAt: now }),
      db.insert(businessAuditEvents).values({ actorEmail: identity.email, action: "project.progress.updated", entityType: "project", entityId: id, detail: `${phase} · ${progress}%`, createdAt: now }),
    ]);
    return Response.json({ project: updated });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    const { identity, db, membership } = await authorizeProject(request, id);
    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "");
    const now = new Date().toISOString();

    if (action === "task") {
      if (!hasProjectPermission(identity, true) && !["project_manager", "technical"].includes(membership?.role ?? "")) {
        return Response.json({ error: "Projektfeladatot csak a projektmenedzser vagy műszaki munkatárs hozhat létre." }, { status: 403 });
      }
      const title = String(body.title ?? "").trim();
      const due = String(body.due ?? "").trim();
      const taskAction = String(body.taskAction ?? "").trim();
      const assignedToEmail = String(body.assignedToEmail ?? "").trim().toLowerCase() || null;
      const severity = body.severity === "high" ? "high" as const : "normal" as const;
      if (!title || !taskAction || !/^\d{4}-\d{2}-\d{2}$/.test(due)) {
        return Response.json({ error: "A feladat neve, végrehajtási leírása és érvényes határideje kötelező." }, { status: 400 });
      }
      if (assignedToEmail && !(await db.select().from(projectMembers).where(and(
        eq(projectMembers.projectId, id), eq(projectMembers.email, assignedToEmail),
      )).limit(1))[0]) {
        return Response.json({ error: "A felelős még nincs a projekthez rendelve." }, { status: 409 });
      }
      const task = {
        id: `PT-${crypto.randomUUID().toUpperCase()}`, projectId: id, source: "internal",
        title, due, status: "waiting_customer" as const, severity, action: taskAction,
        assignedToEmail, createdByEmail: identity.email, createdAt: now, updatedAt: now,
      };
      await db.batch([
        db.insert(projectTasks).values(task),
        db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "task.created", entityType: "task", entityId: task.id, detail: `${title} · ${assignedToEmail || "nincs felelős"}`, createdAt: now }),
      ]);
      return Response.json({ task }, { status: 201 });
    }

    if (action === "comment") {
      const entityType = String(body.entityType ?? "project") as "project" | "task" | "change" | "document";
      const entityId = String(body.entityId ?? id).trim();
      const commentBody = String(body.body ?? "").trim();
      const mentions = Array.isArray(body.mentions) ? body.mentions.map(String).map((value) => value.trim().toLowerCase()).filter(Boolean) : [];
      if (!["project", "task", "change", "document"].includes(entityType) || !entityId || !commentBody || commentBody.length > 5000) {
        return Response.json({ error: "Érvényes hivatkozás és legfeljebb 5000 karakteres megjegyzés szükséges." }, { status: 400 });
      }
      const [comment] = await db.insert(projectComments).values({ projectId: id, entityType, entityId, authorEmail: identity.email, body: commentBody, mentionsJson: JSON.stringify(mentions), createdAt: now }).returning();
      await db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "comment.created", entityType, entityId, detail: commentBody.slice(0, 200), createdAt: now });
      return Response.json({ comment }, { status: 201 });
    }

    if (action === "message") {
      const topic = String(body.topic ?? "Belső projektüzenet").trim();
      const messageBody = String(body.body ?? "").trim();
      if (!topic || !messageBody || messageBody.length > 5000) return Response.json({ error: "A tárgy és az üzenet kötelező." }, { status: 400 });
      const [message] = await db.insert(projectMessages).values({ projectId: id, authorEmail: identity.email, topic, body: messageBody, createdAt: now }).returning();
      await db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "message.created", entityType: "message", entityId: String(message.id), detail: topic, createdAt: now });
      return Response.json({ message }, { status: 201 });
    }

    if (action === "member") {
      if (!hasProjectPermission(identity, true) && membership?.role !== "project_manager") {
        return Response.json({ error: "Projekttagot csak a projektmenedzser rendelhet hozzá." }, { status: 403 });
      }
      const email = String(body.email ?? "").trim().toLowerCase();
      const role = String(body.role ?? "") as InternalProjectRole;
      if (!email.includes("@") || !["project_manager", "technical", "finance", "warranty"].includes(role)) {
        return Response.json({ error: "Érvényes munkatársi email és projektszerep kötelező." }, { status: 400 });
      }
      const existingMember = (await db.select().from(projectMembers).where(and(
        eq(projectMembers.projectId, id), eq(projectMembers.email, email),
      )).limit(1))[0];
      if (existingMember && ["customer", "contact"].includes(existingMember.role)) {
        return Response.json({ error: "Ügyfél vagy kapcsolattartó belső projektszerepre nem írható át." }, { status: 409 });
      }
      await db.insert(projectMembers).values({ projectId: id, email, role, createdAt: now }).onConflictDoUpdate({
        target: [projectMembers.projectId, projectMembers.email], set: { role },
      });
      await db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "member.assigned", entityType: "member", entityId: email, detail: role, createdAt: now });
      return Response.json({ member: { projectId: id, email, role, createdAt: now } }, { status: 201 });
    }

    return Response.json({ error: "Ismeretlen projektművelet." }, { status: 400 });
  } catch (error) { return jsonError(error); }
}
