import { eq } from "drizzle-orm";
import { getDb } from "@/db";
import {
  projectChanges,
  projectDecisions,
  projectMembers,
  projects,
  projectTasks,
} from "@/db/schema";
import type { CrmIdentity } from "@/lib/crm-auth";

export const PILOT_PROJECT_ID = "PRJ-2026-014";

export async function seedMyImperialIfEmpty(identity: CrmIdentity) {
  const db = await getDb();
  const [existing] = await db.select({ id: projects.id }).from(projects)
    .where(eq(projects.id, PILOT_PROJECT_ID)).limit(1);
  const now = new Date().toISOString();

  if (!existing) {
    await db.insert(projects).values({
      id: PILOT_PROJECT_ID,
      portalCode: "MI-2026-014",
      customerName: identity.name,
      customerEmail: identity.email,
      title: "Ürömi családi ház",
      status: "planning",
      phase: "Tervezési szakasz",
      progress: 42,
      targetCompletion: "2027. május",
      handoverDate: null,
      createdAt: now,
      updatedAt: now,
    }).onConflictDoNothing();

    await db.insert(projectTasks).values([
      { id: "TSK-PC-031", projectId: PILOT_PROJECT_ID, source: "PlanCheck", title: "Telek tulajdoni lap feltöltése", due: "július 22.", status: "waiting_customer", action: "Fájl feltöltése", severity: "high", createdAt: now, updatedAt: now },
      { id: "TSK-TEC-018", projectId: PILOT_PROJECT_ID, source: "Technical", title: "Konyhai gépek teljesítményigénye", due: "július 25.", status: "waiting_customer", action: "Adatok megadása", severity: "normal", createdAt: now, updatedAt: now },
      { id: "TSK-FIN-007", projectId: PILOT_PROJECT_ID, source: "Finance", title: "Finanszírozási konstrukció visszaigazolása", due: "július 29.", status: "waiting_customer", action: "Visszaigazolás", severity: "normal", createdAt: now, updatedAt: now },
      { id: "TSK-PC-024", projectId: PILOT_PROJECT_ID, source: "PlanCheck", title: "Geodéziai felmérés ellenőrzése", due: "Lezárva július 9.", status: "completed", action: "Megtekintés", severity: "normal", createdAt: now, updatedAt: now },
    ]).onConflictDoNothing();

    await db.insert(projectChanges).values([
      { id: "CHG-2026-004", projectId: PILOT_PROJECT_ID, title: "Nappali teraszajtó szélesítése", origin: "Ügyféligény", scope: "A 240 cm-es nyílászáró 300 cm-re módosítása, statikai és áthidaló ellenőrzéssel.", customerPriceImpact: "+1 180 000 Ft", scheduleImpact: "+4 munkanap", internalControlStatus: "passed", status: "customer_approval", evidence: "Műszaki lap v2 · költségszámítás v1", createdAt: "2026-07-17T09:00:00.000Z", updatedAt: now },
      { id: "CHG-2026-003", projectId: PILOT_PROJECT_ID, title: "Gépészeti helyiség áthelyezése", origin: "Tervezői javaslat", scope: "A gépészeti tér átszervezése a csőhossz és karbantarthatóság javítására.", customerPriceImpact: "0 Ft", scheduleImpact: "Nincs hatás", internalControlStatus: "passed", status: "approved", evidence: "Alaprajz v4 · gépészeti állásfoglalás", createdAt: "2026-07-11T09:00:00.000Z", updatedAt: now, customerDecisionAt: "2026-07-11T14:20:00.000Z", decidedByEmail: identity.email },
      { id: "CHG-2026-002", projectId: PILOT_PROJECT_ID, title: "Plusz tetőablak", origin: "Ügyféligény", scope: "Egy további 78×118 cm-es tetőablak beépítése.", customerPriceImpact: "+420 000 Ft", scheduleImpact: "+1 munkanap", internalControlStatus: "passed", status: "rejected", evidence: "Árkalkuláció és tetőmetszet", createdAt: "2026-06-28T09:00:00.000Z", updatedAt: now, customerDecisionAt: "2026-06-30T12:10:00.000Z", decidedByEmail: identity.email },
    ]).onConflictDoNothing();

    await db.insert(projectDecisions).values([
      { projectId: PILOT_PROJECT_ID, title: "Építészeti alaprajz v4", area: "Tervezés", due: "Határidő: július 22.", impact: "A szakági tervezés csak jóváhagyás után indulhat.", status: "open", response: "", createdAt: now, updatedAt: now },
      { projectId: PILOT_PROJECT_ID, title: "Külső nyílászárók színe", area: "Anyagválasztás", due: "Határidő: július 28.", impact: "Javaslat: RAL 7016 antracit, kívül-belül.", status: "open", response: "", createdAt: now, updatedAt: now },
      { projectId: PILOT_PROJECT_ID, title: "Gépészeti koncepció", area: "Műszaki tartalom", due: "Jóváhagyva július 11.", impact: "Levegő–víz hőszivattyú, padlófűtés.", status: "approved", response: "Jóváhagyva", decidedAt: "2026-07-11T10:30:00.000Z", decidedByEmail: identity.email, createdAt: now, updatedAt: now },
    ]);
  }

  if (!existing || identity.role === "admin") {
    await db.insert(projectMembers).values({
      projectId: PILOT_PROJECT_ID,
      email: identity.email,
      role: "customer",
      createdAt: now,
    }).onConflictDoNothing();
  }
}
