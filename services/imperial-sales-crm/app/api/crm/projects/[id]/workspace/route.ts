import { and, asc, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import {
  businessAuditEvents,
  businessPartners,
  procurementRequests,
  projectComments,
  projectDocuments,
  projectEvents,
  projectMembers,
  projectMessages,
  projectSiteLogs,
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
    const [tasks, comments, messages, documents, members, events, siteLogs, procurement, partners] = await Promise.all([
      db.select().from(projectTasks).where(eq(projectTasks.projectId, id)).orderBy(asc(projectTasks.due)),
      db.select().from(projectComments).where(eq(projectComments.projectId, id)).orderBy(desc(projectComments.createdAt)),
      db.select().from(projectMessages).where(eq(projectMessages.projectId, id)).orderBy(desc(projectMessages.createdAt)),
      db.select().from(projectDocuments).where(eq(projectDocuments.projectId, id)).orderBy(desc(projectDocuments.updatedAt)),
      db.select().from(projectMembers).where(eq(projectMembers.projectId, id)).orderBy(asc(projectMembers.role)),
      db.select().from(projectEvents).where(eq(projectEvents.projectId, id)).orderBy(desc(projectEvents.createdAt)).limit(100),
      db.select().from(projectSiteLogs).where(eq(projectSiteLogs.projectId, id)).orderBy(desc(projectSiteLogs.logDate)).limit(100),
      db.select().from(procurementRequests).where(eq(procurementRequests.projectId, id)).orderBy(asc(procurementRequests.requiredBy)),
      db.select().from(businessPartners).where(eq(businessPartners.workspaceId, process.env.CRM_WORKSPACE_ID ?? "imperial-live")).orderBy(asc(businessPartners.name)).limit(500),
    ]);
    return Response.json({ identity, membership, project, tasks, comments, messages, documents, members, events, siteLogs, procurement, partners });
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
    if (body.action === "procurement_status") {
      const requestId = String(body.requestId ?? "");
      const nextStatus = String(body.status ?? "") as "requested" | "ordered" | "delivered" | "cancelled";
      const transitions = { draft: ["requested", "cancelled"], requested: ["ordered", "cancelled"], ordered: ["delivered", "cancelled"], delivered: [], cancelled: [] } as const;
      const procurement = (await db.select().from(procurementRequests).where(and(
        eq(procurementRequests.id, requestId), eq(procurementRequests.projectId, id),
      )).limit(1))[0];
      if (!procurement) return Response.json({ error: "A beszerzési igény nem található." }, { status: 404 });
      if (!(transitions[procurement.status] as readonly string[]).includes(nextStatus)) return Response.json({ error: "Ez a beszerzési állapotváltás nem engedélyezett." }, { status: 409 });
      if (!hasProjectPermission(identity, true) && !["project_manager", "technical"].includes(membership?.role ?? "")) {
        return Response.json({ error: "A beszerzés állapotát csak projektvezető vagy műszaki munkatárs módosíthatja." }, { status: 403 });
      }
      const now = new Date().toISOString();
      const [updatedRequest] = await db.update(procurementRequests).set({ status: nextStatus, updatedAt: now }).where(eq(procurementRequests.id, requestId)).returning();
      await db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: `procurement.${nextStatus}`, entityType: "procurement", entityId: requestId, detail: procurement.title, createdAt: now });
      return Response.json({ procurement: updatedRequest });
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

    if (action === "site_log") {
      if (!hasProjectPermission(identity, true) && !["project_manager", "technical"].includes(membership?.role ?? "")) {
        return Response.json({ error: "Építési naplót csak projektvezető vagy műszaki munkatárs rögzíthet." }, { status: 403 });
      }
      const logDate = String(body.logDate ?? "").trim();
      const weather = String(body.weather ?? "").trim();
      const workforce = Math.round(Number(body.workforce ?? -1));
      const summary = String(body.summary ?? "").trim();
      const blockers = String(body.blockers ?? "").trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(logDate) || !weather || !Number.isSafeInteger(workforce) || workforce < 0 || !summary) {
        return Response.json({ error: "A nap, időjárás, létszám és elvégzett munka kötelező." }, { status: 400 });
      }
      if ((await db.select({ id: projectSiteLogs.id }).from(projectSiteLogs).where(and(
        eq(projectSiteLogs.projectId, id), eq(projectSiteLogs.logDate, logDate),
      )).limit(1))[0]) return Response.json({ error: "Erre a napra már készült építési napló." }, { status: 409 });
      const [siteLog] = await db.insert(projectSiteLogs).values({ projectId: id, logDate, weather, workforce, summary, blockers, createdByEmail: identity.email, createdAt: now }).returning();
      await db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "site_log.created", entityType: "site_log", entityId: String(siteLog.id), detail: `${logDate} · ${summary}`, createdAt: now });
      return Response.json({ siteLog }, { status: 201 });
    }

    if (action === "procurement") {
      if (!hasProjectPermission(identity, true) && !["project_manager", "technical"].includes(membership?.role ?? "")) {
        return Response.json({ error: "Beszerzési igényt csak projektvezető vagy műszaki munkatárs hozhat létre." }, { status: 403 });
      }
      const title = String(body.title ?? "").trim();
      const category = String(body.category ?? "").trim();
      const quantity = Math.round(Number(body.quantity ?? 0));
      const unit = String(body.unit ?? "").trim();
      const requiredBy = String(body.requiredBy ?? "").trim();
      const budgetAmount = Math.round(Number(body.budgetAmount ?? 0));
      const supplierPartnerId = body.supplierPartnerId ? Number(body.supplierPartnerId) : null;
      if (!title || !category || !Number.isSafeInteger(quantity) || quantity <= 0 || !unit || !/^\d{4}-\d{2}-\d{2}$/.test(requiredBy)
        || !Number.isSafeInteger(budgetAmount) || budgetAmount < 0) {
        return Response.json({ error: "A megnevezés, kategória, pozitív mennyiség, egység, határidő és költségkeret kötelező." }, { status: 400 });
      }
      if (supplierPartnerId && !(await db.select().from(businessPartners).where(and(
        eq(businessPartners.id, supplierPartnerId),
        eq(businessPartners.workspaceId, process.env.CRM_WORKSPACE_ID ?? "imperial-live"),
      )).limit(1))[0]) {
        return Response.json({ error: "A kiválasztott beszállító nem található." }, { status: 404 });
      }
      const procurement = { id: `PO-${crypto.randomUUID().toUpperCase()}`, projectId: id, title, category, quantity, unit, requiredBy, budgetAmount, currency: "HUF", supplierPartnerId, status: "draft" as const, createdByEmail: identity.email, createdAt: now, updatedAt: now };
      await db.batch([
        db.insert(procurementRequests).values(procurement),
        db.insert(projectEvents).values({ projectId: id, actorEmail: identity.email, action: "procurement.created", entityType: "procurement", entityId: procurement.id, detail: `${title} · ${quantity} ${unit} · ${budgetAmount} HUF`, createdAt: now }),
      ]);
      return Response.json({ procurement }, { status: 201 });
    }

    if (action === "partner") {
      if (!hasProjectPermission(identity, true) && membership?.role !== "project_manager") return Response.json({ error: "Partnert csak a projektmenedzser rögzíthet." }, { status: 403 });
      const name = String(body.name ?? "").trim();
      const partnerType = String(body.partnerType ?? "supplier") as "subcontractor" | "supplier" | "designer" | "architect" | "b2b_partner";
      const email = String(body.email ?? "").trim().toLowerCase() || null;
      if (!name || !["subcontractor", "supplier", "designer", "architect", "b2b_partner"].includes(partnerType) || (email && !email.includes("@"))) {
        return Response.json({ error: "A partner neve, típusa és érvényes email-címe szükséges." }, { status: 400 });
      }
      const identityKey = `${partnerType}:${name.toLocaleLowerCase("hu-HU").replace(/[^a-z0-9áéíóöőúüű]+/gi, "-")}`;
      if ((await db.select({ id: businessPartners.id }).from(businessPartners).where(and(
        eq(businessPartners.workspaceId, process.env.CRM_WORKSPACE_ID ?? "imperial-live"),
        eq(businessPartners.identityKey, identityKey),
      )).limit(1))[0]) return Response.json({ error: "Ez a partner már szerepel a partnertörzsben." }, { status: 409 });
      const [partner] = await db.insert(businessPartners).values({ workspaceId: process.env.CRM_WORKSPACE_ID ?? "imperial-live", identityKey, partnerType, name, email, phone: String(body.phone ?? "").trim() || null, location: String(body.location ?? "").trim() || null, specialties: String(body.specialties ?? "").trim() || null, recordStatus: "prospect", matchConfidence: 100, metadataJson: JSON.stringify({ source: "manual", createdBy: identity.email }), createdAt: now, updatedAt: now }).returning();
      await db.insert(businessAuditEvents).values({ actorEmail: identity.email, action: "business_partner.created", entityType: "business_partner", entityId: String(partner.id), detail: `${partnerType} · ${name}`, createdAt: now });
      return Response.json({ partner }, { status: 201 });
    }

    return Response.json({ error: "Ismeretlen projektművelet." }, { status: 400 });
  } catch (error) { return jsonError(error); }
}
