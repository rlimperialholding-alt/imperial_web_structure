import { and, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import { projectMembers, projects } from "@/db/schema";
import { requireCrmIdentity } from "@/lib/crm-auth";
import { seedMyImperialIfEmpty } from "@/lib/myimperial-seed";

function requestedProject(request: Request, explicitProjectId?: string) {
  if (explicitProjectId?.trim()) return explicitProjectId.trim();
  const url = new URL(request.url);
  return (
    url.searchParams.get("projectId")?.trim()
    || request.headers.get("x-imperial-project-id")?.trim()
    || ""
  );
}

export async function requireProjectAccess(
  request: Request,
  explicitProjectId?: string,
) {
  const identity = await requireCrmIdentity(request);
  await seedMyImperialIfEmpty(identity);
  const db = await getDb();
  const selectedProjectId = requestedProject(request, explicitProjectId);

  let membership = selectedProjectId
    ? (await db.select().from(projectMembers).where(and(
        eq(projectMembers.projectId, selectedProjectId),
        eq(projectMembers.email, identity.email),
      )).limit(1))[0]
    : (await db.select().from(projectMembers)
        .where(eq(projectMembers.email, identity.email))
        .orderBy(desc(projectMembers.createdAt)))[0];

  let projectId = membership?.projectId ?? selectedProjectId;

  if (!membership && identity.role === "admin") {
    const project = projectId
      ? (await db.select({ id: projects.id }).from(projects)
          .where(eq(projects.id, projectId)).limit(1))[0]
      : (await db.select({ id: projects.id }).from(projects)
          .orderBy(desc(projects.updatedAt)).limit(1))[0];
    if (project) {
      projectId = project.id;
      membership = {
        projectId,
        email: identity.email,
        role: "project_manager" as const,
        createdAt: new Date().toISOString(),
      };
    }
  }

  if (!membership || !projectId) {
    throw new Response(
      selectedProjectId
        ? "Ehhez a projekthez nincs hozzáférésed."
        : "Nincs a felhasználóhoz rendelt MyImperial projekt.",
      { status: selectedProjectId ? 403 : 404 },
    );
  }
  return { identity, membership, projectId };
}

export function formatPortalDate(value: string) {
  return new Intl.DateTimeFormat("hu-HU", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "Europe/Budapest",
  }).format(new Date(value));
}
