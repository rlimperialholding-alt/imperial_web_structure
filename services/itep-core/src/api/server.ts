import Fastify from "fastify";
import { PrismaClient } from "@prisma/client";
import { randomUUID } from "node:crypto";
import { ZodError } from "zod";
import { BasicAuthorizationService } from "../application/basic-authorization.js";
import { TaskApplicationService } from "../application/task-service.js";
import { DomainValidationError, InvalidTransitionError } from "../domain/index.js";
import {
  PrismaAuditRepository, PrismaNotificationOutbox, PrismaTaskRepository,
  PrismaIntegrationControlRoomRepository,
} from "../infrastructure/index.js";
import { HumanAnneIncidentService } from "../human-anne/incident-service.js";
import { PrismaHumanAnneIncidentRepository } from "../infrastructure/prisma-human-anne-repository.js";
import { registerHumanAnneRoutes } from "./human-anne-routes.js";
import { registerReportingRoutes } from "./reporting-routes.js";
import { registerIngestionRoutes } from "./ingestion-routes.js";
import { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { IngestionRuleEngine, defaultIngestionRules } from "../ingestion/rules.js";
import { DefaultTaskCandidateDeduplicator } from "../ingestion/deduplicator.js";
import { TaskApplicationCandidateCreator } from "../ingestion/task-candidate-adapter.js";
import { PrismaSourceEventRepository } from "../infrastructure/prisma-source-event-repository.js";
import { PrismaIngestionDedupLookup } from "../infrastructure/prisma-ingestion-dedup-lookup.js";
import { PrismaIngestionReviewQueue } from "../infrastructure/prisma-ingestion-review-queue.js";
import { PrismaReportingRepository } from "../infrastructure/prisma-reporting-repository.js";
import { MetricsEngine } from "../reporting/metrics-engine.js";
import { ExecutiveBriefingGenerator } from "../reporting/briefing-generator.js";
import { ReportingService } from "../reporting/reporting-service.js";
import { createTaskSchema, evidenceSchema, transitionSchema } from "./schemas.js";
import { loadConfig } from "../config/env.js";
import { IdentityVerifier } from "../security/identity-verifier.js";
import { registerIdentityHook } from "./identity-hook.js";
import { registerRateLimit } from "./rate-limit.js";
import { registerOpenApi } from "./openapi.js";
import { registerHealthRoutes } from "./health-routes.js";
import { registerIntegrationControlRoomRoutes } from "./integration-control-room-routes.js";
import { IntegrationControlRoomService } from "../integration-control-room/service.js";
import type { ConnectorOperationExecutor } from "../integration-control-room/ports.js";
import { HumanAnnePublisherAdapter } from "../integration-control-room/adapters.js";
import {
  PrismaConnectorAccountRepository,
  PrismaSyncCheckpointRepository,
} from "../infrastructure/prisma-connector-repositories.js";
import { EnvironmentConnectorSecretProvider } from "../connectors/environment-secret-provider.js";
import { createConnectorAdapters } from "../connectors/connector-adapter-factory.js";
import { ConnectorSyncOrchestrator } from "../connectors/sync-orchestrator.js";
import { registerConnectorRoutes } from "./connector-routes.js";
import { OrchestratorOperationExecutor } from "../integration-control-room/adapters.js";
import { registerOrchestrationRoutes } from "./orchestration-routes.js";

export interface ServerDependencies {
  integrationExecutor?: ConnectorOperationExecutor;
}

export async function buildServer(
  prisma = new PrismaClient(), dependencies: ServerDependencies = {},
) {
  const config = loadConfig();
  const app = Fastify({ logger: true });
  await registerOpenApi(app);
  await registerRateLimit(app, { max: config.API_RATE_LIMIT_MAX, timeWindow: config.API_RATE_LIMIT_WINDOW_MS });
  registerIdentityHook(app, new IdentityVerifier(config.IDENTITY_SHARED_SECRET, () => new Date()));
  registerHealthRoutes(app, prisma);

  const tasks = new PrismaTaskRepository(prisma);
  const audit = new PrismaAuditRepository(prisma);
  const outbox = new PrismaNotificationOutbox(prisma);
  const service = new TaskApplicationService(
    tasks, audit, outbox, new BasicAuthorizationService(),
    { now: () => new Date() }, { next: () => `ITEP-${randomUUID()}` },
  );
  const humanAnneService = new HumanAnneIncidentService(
    new PrismaHumanAnneIncidentRepository(prisma),
    { now: () => new Date() }, { next: () => `HA-${randomUUID()}` },
  );
  const reportingService = new ReportingService(
    new PrismaReportingRepository(prisma), new MetricsEngine(),
    new ExecutiveBriefingGenerator(), { now: () => new Date() },
  );
  const ingestionActor = {
    actorId: "digital-anne", organizationId: config.DEFAULT_ORGANIZATION_ID,
    roles: ["SYSTEM"], permissions: ["task.create","task.read.all","task.transition.all",
      "task.sensitive.legal","task.sensitive.financial","task.sensitive.authority",
      "task.sensitive.hr","task.sensitive.confidential"],
  };
  const ingestionService = new SourceIngestionService(
    new PrismaSourceEventRepository(prisma),
    new IngestionRuleEngine(defaultIngestionRules()),
    new DefaultTaskCandidateDeduplicator(new PrismaIngestionDedupLookup(prisma)),
    new TaskApplicationCandidateCreator(service, ingestionActor, {
      resolveAssignee: () => config.DEFAULT_ASSIGNEE_ID,
      resolveEscalationPerson: () => config.DEFAULT_ESCALATION_PERSON_ID,
      resolveContactEmail: () => config.DEFAULT_CONTACT_EMAIL,
    }),
    new PrismaIngestionReviewQueue(prisma), { now: () => new Date() },
  );
  const connectorAccounts = new PrismaConnectorAccountRepository(prisma);
  const connectorCheckpoints = new PrismaSyncCheckpointRepository(prisma);
  const connectorSecrets = new EnvironmentConnectorSecretProvider();
  let controlRoom: IntegrationControlRoomService;
  const syncObserver = {
    async success(input: {
      organizationId: string; connectorId: string; kind: string;
    }) {
      await controlRoom.recordConnectorSuccess(input);
    },
    async failure(input: {
      organizationId: string; connectorId: string; kind: string;
      errorMessage: string; reauthRequired: boolean;
    }) {
      await controlRoom.recordConnectorFailure(input);
    },
  };
  const connectorOrchestrator = new ConnectorSyncOrchestrator(
    connectorAccounts,
    connectorCheckpoints,
    connectorSecrets,
    createConnectorAdapters(ingestionService, {
      billingoBaseUrl: config.BILLINGO_API_BASE_URL,
      metaGraphBaseUrl: config.META_GRAPH_API_BASE_URL,
      metaGraphApiVersion: config.META_GRAPH_API_VERSION,
      googleAdsBaseUrl: config.GOOGLE_ADS_API_BASE_URL,
      googleAdsApiVersion: config.GOOGLE_ADS_API_VERSION,
      googleOauthTokenUrl: config.GOOGLE_OAUTH_TOKEN_URL,
      bankBaseUrl: config.BANK_API_BASE_URL,
      crmBaseUrl: config.CRM_API_BASE_URL,
      crmActivitiesPath: config.CRM_ACTIVITIES_PATH,
      crmAuthHeader: config.CRM_AUTH_HEADER,
      crmAuthScheme: config.CRM_AUTH_SCHEME,
      crmWorkspaceQueryParameter: config.CRM_WORKSPACE_QUERY_PARAMETER,
    }),
    humanAnneService,
    { now: () => new Date() },
    { next: () => randomUUID() },
    syncObserver,
  );
  controlRoom = new IntegrationControlRoomService(
    new PrismaIntegrationControlRoomRepository(prisma),
    dependencies.integrationExecutor ??
      new OrchestratorOperationExecutor(connectorOrchestrator),
    new HumanAnnePublisherAdapter(humanAnneService),
    () => new Date(),
  );

  registerConnectorRoutes(app, connectorOrchestrator);
  registerHumanAnneRoutes(app, humanAnneService);
  registerReportingRoutes(app, reportingService);
  registerIngestionRoutes(app, ingestionService);
  registerIntegrationControlRoomRoutes(app, controlRoom);
  registerOrchestrationRoutes(app, prisma, service, {
    issuerId: "smart-calendar",
    escalationPersonId: config.DEFAULT_ESCALATION_PERSON_ID,
    contactEmail: config.DEFAULT_CONTACT_EMAIL,
  });

  app.post("/v1/tasks", async (request, reply) => {
    const actor = requireActor(request.verifiedActor);
    const task = await service.create(actor, createTaskSchema.parse(request.body));
    return reply.code(201).send(serializeTask(task));
  });
  app.get<{ Params: { id: string } }>("/v1/tasks/:id", async (request, reply) => {
    const actor = requireActor(request.verifiedActor);
    const task = await tasks.getById(request.params.id);
    if (!task) return reply.code(404).send({ error: "TASK_NOT_FOUND" });
    new BasicAuthorizationService().assertCanReadTask(actor, task);
    return serializeTask(task);
  });
  app.post<{ Params: { id: string } }>("/v1/tasks/:id/transitions", async (request, reply) => {
    const actor = requireActor(request.verifiedActor);
    const { target } = transitionSchema.parse(request.body);
    // JSON-only Fastify API: a request.body tartalmát a transitionSchema zod-validálja,
    // a service réteg tartósan tárolja, a válasz a szerver-oldali task entitás
    // szerializált formája -- nincs nyers reflexió HTML-válaszba.
    return reply.send(serializeTask(await service.transition(actor, request.params.id, target))); // nosemgrep: javascript.express.security.audit.xss.direct-response-write.direct-response-write
  });
  app.post<{ Params: { id: string } }>("/v1/tasks/:id/evidence", async (request, reply) => {
    const actor = requireActor(request.verifiedActor);
    const task = await service.addEvidence(actor, request.params.id, evidenceSchema.parse(request.body));
    // JSON-only Fastify API: a request.body tartalmát az evidenceSchema zod-validálja,
    // a service réteg tartósan tárolja, a válasz a szerver-oldali task entitás
    // szerializált formája -- nincs nyers reflexió HTML-válaszba.
    return reply.code(201).send(serializeTask(task)); // nosemgrep: javascript.express.security.audit.xss.direct-response-write.direct-response-write
  });
  app.post("/internal/enforcement/run", async (_request, reply) =>
    reply.send({ processed: await service.runEnforcementBatch(100) }),
  );

  app.setErrorHandler((error, _request, reply) => {
    const message = error instanceof Error ? error.message : String(error);
    if (error instanceof ZodError) return reply.code(400).send({ error: "VALIDATION_ERROR", details: error.issues });
    if (error instanceof DomainValidationError) return reply.code(422).send({ error: "DOMAIN_VALIDATION_ERROR", message: error.message });
    if (error instanceof InvalidTransitionError) return reply.code(409).send({ error: "INVALID_TRANSITION", message: error.message });
    if (/identity|actor|required|signature|expired/i.test(message)) return reply.code(401).send({ error: "IDENTITY_REQUIRED", message });
    app.log.error({ err: error }, "Unhandled API error");
    return reply.code(500).send({ error: "INTERNAL_ERROR" });
  });
  app.addHook("onClose", async () => { await prisma.$disconnect(); });
  return app;
}

function requireActor(actor: any) {
  if (!actor) throw new Error("Verified actor is required");
  return actor;
}
function serializeTask(task: any) {
  return { ...task, createdAt: task.createdAt.toISOString(), dueAt: task.dueAt.toISOString(),
    nextCheckAt: task.nextCheckAt.toISOString(), lastCheckedAt: task.lastCheckedAt?.toISOString(),
    acceptedAt: task.acceptedAt?.toISOString(), evidenceSubmissions: task.evidenceSubmissions.map((e: any) =>
      ({ ...e, submittedAt: e.submittedAt.toISOString() })) };
}
