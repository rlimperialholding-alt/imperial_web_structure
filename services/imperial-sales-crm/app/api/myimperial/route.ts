import { asc, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectChanges, projectDecisions, projectMembers, projects, projectTasks, warrantyCases } from "@/db/schema";
import { jsonError } from "@/lib/crm-auth";
import { requireProjectAccess } from "@/lib/myimperial-auth";

export async function GET(request: Request) {
  try {
    const { identity, membership, projectId } = await requireProjectAccess(request);
    const db = await getDb();
    const [projectRows, tasks, changes, decisions, cases, availableProjects] = await Promise.all([
      db.select().from(projects).where(eq(projects.id, projectId)).limit(1),
      db.select().from(projectTasks).where(eq(projectTasks.projectId, projectId)).orderBy(asc(projectTasks.id)),
      db.select().from(projectChanges).where(eq(projectChanges.projectId, projectId)).orderBy(desc(projectChanges.createdAt)),
      db.select().from(projectDecisions).where(eq(projectDecisions.projectId, projectId)).orderBy(asc(projectDecisions.id)),
      db.select().from(warrantyCases).where(eq(warrantyCases.projectId, projectId)).orderBy(desc(warrantyCases.createdAt)),
      identity.role === "admin"
        ? db.select().from(projects).orderBy(desc(projects.updatedAt))
        : db.select({
            id: projects.id,
            portalCode: projects.portalCode,
            customerName: projects.customerName,
            customerEmail: projects.customerEmail,
            title: projects.title,
            status: projects.status,
            phase: projects.phase,
            progress: projects.progress,
            targetCompletion: projects.targetCompletion,
            handoverDate: projects.handoverDate,
            createdAt: projects.createdAt,
            updatedAt: projects.updatedAt,
          }).from(projects).innerJoin(
            projectMembers,
            eq(projectMembers.projectId, projects.id),
          ).where(eq(projectMembers.email, identity.email))
            .orderBy(desc(projects.updatedAt)),
    ]);
    const project = projectRows[0];
    if (!project) return Response.json({ error: "A projekt nem található." }, { status: 404 });
    return Response.json({
      identity,
      membership,
      project,
      tasks,
      changes: changes.map(({ internalControlStatus, ...change }) => ({
        ...change,
        internalControl: internalControlStatus === "pending" ? "Ellenőrzés alatt" : internalControlStatus === "passed" ? "Belső kontroll teljesült" : "Vezetői kontroll alatt",
      })),
      decisions,
      warrantyCases: cases,
      availableProjects,
    });
  } catch (error) { return jsonError(error); }
}
