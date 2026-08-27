import { and, asc, desc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import {
  activities,
  businessPartners,
  businessProjects,
  importReviewItems,
  projectEvents,
  projects,
  sourceRecords,
  tasks,
} from "@/db/schema";

export type IntelligenceModuleState = "ready" | "testable" | "blocked";

const moduleCatalog: {
  key: string;
  name: string;
  owner: string;
  state: IntelligenceModuleState;
  evidence: string;
  productionGate?: string;
}[] = [
  { key: "crm", name: "Ügyfélkapcsolati nyilvántartás", owner: "Értékesítő", state: "ready", evidence: "Tartós lead-, feladat- és ügyféladatok" },
  { key: "lead-generator", name: "Leadgenerátor", owner: "Marketinges", state: "testable", evidence: "Gmail- és űrlapforrásból importált érdeklődők", productionGate: "Folyamatos Gmail webhook és jóváhagyott kampányforrások" },
  { key: "marketing", name: "Marketing-automatizálás", owner: "Marketinges", state: "testable", evidence: "Kampány- és publikációs kapuk az Integration Hubban", productionGate: "Meta/Google Ads hitelesítés és költési limitek" },
  { key: "content", name: "Tartalomgyár", owner: "Marketinges", state: "testable", evidence: "Forrás-, jóváhagyási és visszaállítási folyamat", productionGate: "Éles Directus és webhely-hozzáférések" },
  { key: "housematch", name: "HouseMatch", owner: "Értékesítő", state: "blocked", evidence: "Kézikönyvi döntési szabályok", productionGate: "Jóváhagyott típusház-katalógus és árkapcsolat" },
  { key: "pricing", name: "Árazó, Ártükör és Ütemtükör", owner: "Értékesítő / pénzügyes", state: "blocked", evidence: "Fedezeti és jóváhagyási kapuk specifikálva", productionGate: "Érvényes tételes normatár és vállalati fedezeti szabály" },
  { key: "plotcheck", name: "PlotCheck", owner: "Projektmenedzser", state: "blocked", evidence: "Forrásdokumentumok hivatkozásként elérhetők", productionGate: "Telek-, övezeti és közműadatok jóváhagyott adatmodellje" },
  { key: "engineering", name: "Engineering Portal", owner: "Projektmenedzser", state: "blocked", evidence: "Tervezői adatbázis importálva", productionGate: "Külső tervezői jogosultságok és tervleadási UAT" },
  { key: "plancheck", name: "PlanCheck", owner: "Projektmenedzser", state: "blocked", evidence: "Dokumentum- és bizonyítéklánc rendelkezésre áll", productionGate: "Jóváhagyott szakági ellenőrzési szabályok" },
  { key: "contracts", name: "Szerződésgyár", owner: "Értékesítő", state: "blocked", evidence: "Szerződések és iratforrások importálva", productionGate: "Jóváhagyott iratminták és jogi UAT" },
  { key: "calendar", name: "Okosnaptár", owner: "Projektmenedzser", state: "testable", evidence: "ITEP Calendar ingestion, függőség- és feladatkezelés", productionGate: "Google Calendar hitelesítés és 3–5 ProjectID UAT" },
  { key: "procurement", name: "Beszerző-tendereztető", owner: "Projektmenedzser", state: "testable", evidence: "883 partner és forráskapcsolataik", productionGate: "Ajánlatkérési és megrendelési jóváhagyási UAT" },
  { key: "finance", name: "Pénzügyi modul", owner: "Pénzügyes", state: "ready", evidence: "Tartós számlaadatok és ügyfél-/projektpárosítás", productionGate: "Billingo és bank read-only hitelesítés" },
  { key: "executive", name: "Vezetői összefoglaló", owner: "Ügyvezető", state: "ready", evidence: "Értékesítési, pénzügyi és importeltérések egy képen" },
  { key: "checklists", name: "Ellenőrzőlisták és folyamatkártyák", owner: "Folyamatgazda", state: "ready", evidence: "99 folyamatkártya, bizonyíték- és megállító kapuk" },
  { key: "myimperial", name: "MyImperial", owner: "Projektmenedzser", state: "ready", evidence: "Projekt, döntés, dokumentum, változás és értesítés" },
  { key: "care", name: "Imperial Care", owner: "Projektmenedzser", state: "ready", evidence: "Garanciális ügyazonosító, határidő és visszaigazolás" },
  { key: "sources", name: "Külső adatbázisok és dokumentumok", owner: "Öt belső munkakör", state: "ready", evidence: "Drive/Gmail forrásleltár, csak hivatkozásos nagyfájl-kezelés" },
  { key: "connectors", name: "Külső rendszerkapcsolatok", owner: "Rendszergazda", state: "testable", evidence: "ITEP integrációs vezérlőközpont és hibasor", productionGate: "Szolgáltatásonkénti éles credential és tulajdonosi jóváhagyás" },
  { key: "agents", name: "Mesterséges intelligencia ügynökök", owner: "Ügyvezető", state: "testable", evidence: "Feladatjavaslat, review-sor és emberi döntési korlát", productionGate: "OpenAI API-kulcs, modell- és költséglimit, agentenkénti UAT" },
  { key: "audit", name: "Audit és folytonosság", owner: "Ügyvezető", state: "ready", evidence: "Feladat-, projekt-, import- és döntési eseménynapló" },
];

export async function getIntelligenceWorkspace(workspaceId: string) {
  const db = await getDb();
  const [
    importedProjects,
    portalProjects,
    partners,
    reviews,
    sources,
    crmAudit,
    portalAudit,
    taskRows,
  ] = await Promise.all([
    db.select({
      id: businessProjects.id,
      title: businessProjects.title,
      location: businessProjects.location,
      projectType: businessProjects.projectType,
      status: businessProjects.projectStatus,
      customerMatchStatus: businessProjects.customerMatchStatus,
      updatedAt: businessProjects.updatedAt,
    }).from(businessProjects)
      .where(eq(businessProjects.workspaceId, workspaceId))
      .orderBy(desc(businessProjects.updatedAt))
      .limit(200),
    db.select({
      id: projects.id,
      title: projects.title,
      customerName: projects.customerName,
      status: projects.status,
      phase: projects.phase,
      progress: projects.progress,
      targetCompletion: projects.targetCompletion,
      updatedAt: projects.updatedAt,
    }).from(projects).orderBy(desc(projects.updatedAt)).limit(100),
    db.select({
      id: businessPartners.id,
      name: businessPartners.name,
      partnerType: businessPartners.partnerType,
      location: businessPartners.location,
      specialties: businessPartners.specialties,
      status: businessPartners.recordStatus,
      matchConfidence: businessPartners.matchConfidence,
      updatedAt: businessPartners.updatedAt,
    }).from(businessPartners)
      .where(eq(businessPartners.workspaceId, workspaceId))
      .orderBy(desc(businessPartners.updatedAt))
      .limit(200),
    db.select({
      id: importReviewItems.id,
      entityType: importReviewItems.entityType,
      reasonCode: importReviewItems.reasonCode,
      summary: importReviewItems.summary,
      status: importReviewItems.status,
      sourceTitle: sourceRecords.title,
      sourceUrl: sourceRecords.sourceUrl,
      createdAt: importReviewItems.createdAt,
    }).from(importReviewItems)
      .innerJoin(sourceRecords, eq(importReviewItems.sourceRecordId, sourceRecords.id))
      .where(and(
        eq(importReviewItems.workspaceId, workspaceId),
        eq(importReviewItems.status, "open"),
      ))
      .orderBy(desc(importReviewItems.createdAt))
      .limit(200),
    db.select({
      id: sourceRecords.id,
      title: sourceRecords.title,
      recordType: sourceRecords.recordType,
      sourceSystem: sourceRecords.sourceSystem,
      sourceUrl: sourceRecords.sourceUrl,
      reviewStatus: sourceRecords.reviewStatus,
      mimeType: sourceRecords.mimeType,
      byteSize: sourceRecords.byteSize,
      updatedAt: sourceRecords.updatedAt,
    }).from(sourceRecords)
      .where(eq(sourceRecords.workspaceId, workspaceId))
      .orderBy(desc(sourceRecords.updatedAt))
      .limit(250),
    db.select({
      id: activities.id,
      actor: activities.actorEmail,
      action: activities.action,
      entityType: activities.entityType,
      entityId: activities.entityId,
      detail: activities.detail,
      createdAt: activities.createdAt,
    }).from(activities).orderBy(desc(activities.createdAt)).limit(150),
    db.select({
      id: projectEvents.id,
      actor: projectEvents.actorEmail,
      action: projectEvents.action,
      entityType: projectEvents.entityType,
      entityId: projectEvents.entityId,
      detail: projectEvents.detail,
      createdAt: projectEvents.createdAt,
    }).from(projectEvents).orderBy(desc(projectEvents.createdAt)).limit(150),
    db.select({
      id: tasks.id,
      title: tasks.title,
      leadName: tasks.leadName,
      type: tasks.type,
      due: tasks.due,
      priority: tasks.priority,
      done: tasks.done,
      ai: tasks.ai,
      ownerEmail: tasks.ownerEmail,
      updatedAt: tasks.updatedAt,
    }).from(tasks).orderBy(asc(tasks.done), asc(tasks.id)).limit(250),
  ]);

  const audit = [
    ...crmAudit.map((event) => ({ ...event, id: `crm-${event.id}`, source: "CRM" })),
    ...portalAudit.map((event) => ({ ...event, id: `portal-${event.id}`, source: "MyImperial" })),
  ].sort((left, right) => right.createdAt.localeCompare(left.createdAt)).slice(0, 200);

  const calendar = [
    ...taskRows.filter((task) => !task.done).map((task) => ({
      id: `task-${task.id}`,
      kind: "task",
      title: task.title,
      context: task.leadName,
      when: task.due,
      priority: task.priority,
      status: "open",
    })),
    ...portalProjects.map((project) => ({
      id: `project-${project.id}`,
      kind: "milestone",
      title: `${project.title} – célátadás`,
      context: project.phase,
      when: project.targetCompletion,
      priority: project.progress < 50 ? "high" : "normal",
      status: project.status,
    })),
  ];

  const agents = [
    { key: "lead-qualifier", name: "Érdeklődő-minősítő", owner: "Értékesítő", purpose: "Szándék, sürgősség és következő kérdések javaslata", forbidden: "Nem utasíthat el végleg és nem ígérhet árat." },
    { key: "sales-helper", name: "Értékesítési segítő", owner: "Értékesítő", purpose: "Beszélgetés-összefoglaló és választervezet", forbidden: "Nem küldhet végleges ajánlatot jóváhagyás nélkül." },
    { key: "content-agent", name: "Tartalomkészítő", owner: "Marketinges", purpose: "Forráshoz kötött tartalomváltozat készítése", forbidden: "Nem találhat ki árat, műszaki vagy jogi ígéretet." },
    { key: "plan-reviewer", name: "Tervellenőrzési segítő", owner: "Projektmenedzser", purpose: "Hiány, ellentmondás és kérdés felismerése", forbidden: "Nem zárhat le blokkoló műszaki hibát." },
    { key: "finance-analyst", name: "Pénzügyi elemző", owner: "Pénzügyes", purpose: "Eltérés, kockázat és előrejelzés összefoglalása", forbidden: "Nem hagyhat jóvá számlát vagy utalást." },
    { key: "procurement-agent", name: "Beszerzési összehasonlító", owner: "Projektmenedzser", purpose: "Ajánlatok és teljes költség összevetése", forbidden: "Nem választhat nyertest." },
    { key: "contract-agent", name: "Szerződés-előkészítő", owner: "Értékesítő", purpose: "Hiány és ellentmondás felismerése", forbidden: "Nem adhat végleges jogi álláspontot." },
    { key: "executive-agent", name: "Vezetői összefoglaló", owner: "Ügyvezető", purpose: "Kritikus ügyek és döntési lehetőségek bemutatása", forbidden: "Nem hozhat vezetői döntést és nem módosíthat szabályt." },
  ];

  return {
    workspaceId,
    generatedAt: new Date().toISOString(),
    modules: moduleCatalog,
    projects: { imported: importedProjects, portal: portalProjects },
    partners,
    reviews,
    sources,
    calendar,
    agents,
    audit,
    taskSummary: {
      total: taskRows.length,
      open: taskRows.filter((task) => !task.done).length,
      aiSuggested: taskRows.filter((task) => task.ai && !task.done).length,
    },
  };
}

