import { randomUUID } from "node:crypto";
import { PrismaClient } from "@prisma/client";
import { BasicAuthorizationService } from "../application/basic-authorization.js";
import { TaskApplicationService } from "../application/task-service.js";
import {
  PrismaAuditRepository, PrismaNotificationOutbox, PrismaTaskRepository,
  PrismaConnectorAccountRepository, PrismaSyncCheckpointRepository,
  PrismaIntegrationControlRoomRepository, PrismaHumanAnneIncidentRepository,
  PrismaSourceEventRepository, PrismaIngestionDedupLookup, PrismaIngestionReviewQueue,
} from "../infrastructure/index.js";
import { PrismaOutboxDispatchRepository } from "../infrastructure/prisma-outbox-dispatch-repository.js";
import { OutboxDispatcher } from "./outbox-dispatcher.js";
import { EnforcementWorker } from "./enforcement-worker.js";
import { OutboxWorker } from "./outbox-worker.js";
import type { EmailSender } from "../notifications/email-sender.js";
import { loadConfig } from "../config/env.js";
import { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { IngestionRuleEngine, defaultIngestionRules } from "../ingestion/rules.js";
import { DefaultTaskCandidateDeduplicator } from "../ingestion/deduplicator.js";
import { TaskApplicationCandidateCreator } from "../ingestion/task-candidate-adapter.js";
import { EnvironmentConnectorSecretProvider } from "../connectors/environment-secret-provider.js";
import { createConnectorAdapters } from "../connectors/connector-adapter-factory.js";
import { ConnectorSyncOrchestrator } from "../connectors/sync-orchestrator.js";
import { ConnectorSyncWorker } from "./connector-sync-worker.js";
import { HumanAnneIncidentService } from "../human-anne/incident-service.js";
import { IntegrationControlRoomService } from "../integration-control-room/service.js";
import { HumanAnnePublisherAdapter, OrchestratorOperationExecutor } from "../integration-control-room/adapters.js";
import { IntegrationRetryWorker } from "./integration-retry-worker.js";

const config = loadConfig();
const prisma = new PrismaClient();
const unsupportedEmailSender: EmailSender = { async send() { throw new Error("Gmail transport is not configured"); } };
const taskService = new TaskApplicationService(
  new PrismaTaskRepository(prisma), new PrismaAuditRepository(prisma),
  new PrismaNotificationOutbox(prisma), new BasicAuthorizationService(),
  { now: () => new Date() }, { next: () => `ITEP-${randomUUID()}` },
);
const ingestion = new SourceIngestionService(
  new PrismaSourceEventRepository(prisma), new IngestionRuleEngine(defaultIngestionRules()),
  new DefaultTaskCandidateDeduplicator(new PrismaIngestionDedupLookup(prisma)),
  new TaskApplicationCandidateCreator(taskService, {
    actorId: "digital-anne", organizationId: config.DEFAULT_ORGANIZATION_ID,
    roles: ["SYSTEM"], permissions: ["task.create","task.read.all","task.transition.all",
      "task.sensitive.legal","task.sensitive.financial","task.sensitive.authority","task.sensitive.hr","task.sensitive.confidential"],
  }, {
    resolveAssignee: () => config.DEFAULT_ASSIGNEE_ID,
    resolveEscalationPerson: () => config.DEFAULT_ESCALATION_PERSON_ID,
    resolveContactEmail: () => config.DEFAULT_CONTACT_EMAIL,
  }), new PrismaIngestionReviewQueue(prisma), { now: () => new Date() },
);
const humanAnne = new HumanAnneIncidentService(
  new PrismaHumanAnneIncidentRepository(prisma), { now: () => new Date() },
  { next: () => `HA-${randomUUID()}` },
);
const accounts = new PrismaConnectorAccountRepository(prisma);
const checkpoints = new PrismaSyncCheckpointRepository(prisma);
const secrets = new EnvironmentConnectorSecretProvider();
let controlRoom: IntegrationControlRoomService;
const syncObserver = {
  async success(input: { organizationId: string; connectorId: string; kind: string }) {
    await controlRoom.recordConnectorSuccess(input);
  },
  async failure(input: { organizationId: string; connectorId: string; kind: string; errorMessage: string; reauthRequired: boolean }) {
    await controlRoom.recordConnectorFailure(input);
  },
};
const orchestrator = new ConnectorSyncOrchestrator(
  accounts, checkpoints, secrets,
  createConnectorAdapters(ingestion, {
    billingoBaseUrl: config.BILLINGO_API_BASE_URL,
    bankBaseUrl: config.BANK_API_BASE_URL,
    crmBaseUrl: config.CRM_API_BASE_URL,
    crmActivitiesPath: config.CRM_ACTIVITIES_PATH,
    crmAuthHeader: config.CRM_AUTH_HEADER,
    crmAuthScheme: config.CRM_AUTH_SCHEME,
    crmWorkspaceQueryParameter: config.CRM_WORKSPACE_QUERY_PARAMETER,
  }), humanAnne, { now: () => new Date() }, { next: () => randomUUID() }, syncObserver,
);
controlRoom = new IntegrationControlRoomService(
  new PrismaIntegrationControlRoomRepository(prisma),
  new OrchestratorOperationExecutor(orchestrator),
  new HumanAnnePublisherAdapter(humanAnne), () => new Date(),
);
const enforcementWorker = new EnforcementWorker(taskService, console, {
  batchSize: Number(process.env.ENFORCEMENT_BATCH_SIZE ?? 100), intervalMs: config.ENFORCEMENT_INTERVAL_MS,
});
const dispatcher = new OutboxDispatcher(new PrismaOutboxDispatchRepository(prisma), unsupportedEmailSender, { now: () => new Date() });
const outboxWorker = new OutboxWorker(dispatcher, console, config.OUTBOX_INTERVAL_MS);
const connectorWorker = new ConnectorSyncWorker(orchestrator, console, config.CONNECTOR_SYNC_INTERVAL_MS);
const retryWorker = new IntegrationRetryWorker(controlRoom, config.INTEGRATION_RETRY_INTERVAL_MS, config.INTEGRATION_RETRY_BATCH_SIZE);

enforcementWorker.start(); outboxWorker.start(); connectorWorker.start(); retryWorker.start();
async function shutdown() {
  enforcementWorker.stop(); outboxWorker.stop(); connectorWorker.stop(); retryWorker.stop();
  await prisma.$disconnect(); process.exit(0);
}
process.on("SIGTERM", () => void shutdown()); process.on("SIGINT", () => void shutdown());
