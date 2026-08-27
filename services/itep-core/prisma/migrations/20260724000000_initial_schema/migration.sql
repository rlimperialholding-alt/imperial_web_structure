-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "TaskPriority" AS ENUM ('P1', 'P2', 'P3', 'P4');

-- CreateEnum
CREATE TYPE "TaskStatus" AS ENUM ('DRAFT', 'ASSIGNED', 'AWAITING_ACKNOWLEDGEMENT', 'IN_PROGRESS', 'WAITING_EXTERNAL', 'BLOCKED', 'SUBMITTED', 'UNDER_REVIEW', 'CHANGES_REQUESTED', 'CLOSED', 'CANCELLED');

-- CreateEnum
CREATE TYPE "AssigneeType" AS ENUM ('EMPLOYEE', 'MANAGER', 'SUBCONTRACTOR', 'PARTNER', 'EXTERNAL_EXPERT', 'SYSTEM');

-- CreateEnum
CREATE TYPE "EvidenceType" AS ENUM ('EMAIL', 'DOCUMENT', 'PHOTO', 'FILE', 'LINK', 'SYSTEM_DATA', 'SIGNATURE', 'APPROVAL', 'OTHER');

-- CreateEnum
CREATE TYPE "SensitivityLevel" AS ENUM ('INTERNAL', 'CONFIDENTIAL', 'LEGAL', 'FINANCIAL', 'AUTHORITY', 'HR');

-- CreateEnum
CREATE TYPE "IncidentSeverity" AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');

-- CreateEnum
CREATE TYPE "IncidentStatus" AS ENUM ('OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED', 'DISMISSED');

-- CreateEnum
CREATE TYPE "SourceKind" AS ENUM ('GMAIL', 'CALENDAR', 'DRIVE', 'MANUAL', 'WEBHOOK');

-- CreateEnum
CREATE TYPE "SourceEventStatus" AS ENUM ('RECEIVED', 'NORMALIZED', 'IGNORED', 'TASK_CREATED', 'NEEDS_REVIEW', 'FAILED');

-- CreateEnum
CREATE TYPE "IngestionReviewStatus" AS ENUM ('OPEN', 'APPROVED', 'REJECTED', 'CONVERTED');

-- CreateEnum
CREATE TYPE "ConnectorKind" AS ENUM ('GMAIL', 'CALENDAR', 'DRIVE', 'BILLINGO', 'BANK', 'CRM');

-- CreateEnum
CREATE TYPE "ConnectorStatus" AS ENUM ('DISCONNECTED', 'CONNECTING', 'ACTIVE', 'DEGRADED', 'ERROR', 'REAUTH_REQUIRED');

-- CreateEnum
CREATE TYPE "WebhookSubscriptionStatus" AS ENUM ('ACTIVE', 'EXPIRED', 'REVOKED');

-- CreateTable
CREATE TABLE "ItepTask" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "sourceExternalId" TEXT,
    "semanticFingerprint" TEXT,
    "issuerId" TEXT NOT NULL,
    "assigneeId" TEXT NOT NULL,
    "assigneeType" "AssigneeType" NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "priority" "TaskPriority" NOT NULL,
    "status" "TaskStatus" NOT NULL DEFAULT 'DRAFT',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "dueAt" TIMESTAMP(3) NOT NULL,
    "acceptanceCriteria" TEXT NOT NULL,
    "evidenceType" "EvidenceType" NOT NULL,
    "evidenceDescription" TEXT NOT NULL,
    "machineVerifiable" BOOLEAN NOT NULL DEFAULT false,
    "escalationPersonId" TEXT NOT NULL,
    "contactEmail" TEXT NOT NULL,
    "contactPhone" TEXT,
    "lastCheckedAt" TIMESTAMP(3),
    "nextCheckAt" TIMESTAMP(3) NOT NULL,
    "reminderLevel" INTEGER NOT NULL DEFAULT 0,
    "acceptedBy" TEXT,
    "acceptedAt" TIMESTAMP(3),
    "rejectionReason" TEXT,
    "blockedReason" TEXT,
    "cancelledReason" TEXT,
    "sensitivity" "SensitivityLevel" NOT NULL DEFAULT 'INTERNAL',
    "version" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "ItepTask_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TaskEvidence" (
    "id" TEXT NOT NULL,
    "taskId" TEXT NOT NULL,
    "type" "EvidenceType" NOT NULL,
    "uri" TEXT NOT NULL,
    "checksum" TEXT,
    "metadata" JSONB,
    "submittedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "submittedBy" TEXT NOT NULL,
    "verifiedAt" TIMESTAMP(3),
    "verifiedBy" TEXT,
    "verificationResult" TEXT,

    CONSTRAINT "TaskEvidence_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TaskAuditEvent" (
    "id" TEXT NOT NULL,
    "taskId" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "actorId" TEXT NOT NULL,
    "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "payload" JSONB NOT NULL,
    "sequence" BIGINT NOT NULL,
    "previousHash" TEXT,
    "hash" TEXT,

    CONSTRAINT "TaskAuditEvent_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "NotificationOutbox" (
    "id" TEXT NOT NULL,
    "taskId" TEXT NOT NULL,
    "eventKey" TEXT NOT NULL,
    "channel" TEXT NOT NULL,
    "recipient" TEXT NOT NULL,
    "cc" TEXT[],
    "subject" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "scheduledFor" TIMESTAMP(3) NOT NULL,
    "sentAt" TIMESTAMP(3),
    "attempts" INTEGER NOT NULL DEFAULT 0,
    "lastError" TEXT,
    "lockedAt" TIMESTAMP(3),
    "deadLetteredAt" TIMESTAMP(3),
    "providerMessageId" TEXT,
    "idempotencyKey" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "NotificationOutbox_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TaskDependency" (
    "id" TEXT NOT NULL,
    "taskId" TEXT NOT NULL,
    "dependsOnId" TEXT NOT NULL,

    CONSTRAINT "TaskDependency_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "HumanAnneIncident" (
    "id" TEXT NOT NULL,
    "taskId" TEXT,
    "category" TEXT NOT NULL,
    "severity" "IncidentSeverity" NOT NULL,
    "status" "IncidentStatus" NOT NULL DEFAULT 'OPEN',
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "recommendedAction" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "acknowledgedAt" TIMESTAMP(3),
    "acknowledgedBy" TEXT,
    "resolvedAt" TIMESTAMP(3),
    "resolvedBy" TEXT,
    "resolution" TEXT,

    CONSTRAINT "HumanAnneIncident_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SourceEvent" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "source" "SourceKind" NOT NULL,
    "externalId" TEXT NOT NULL,
    "occurredAt" TIMESTAMP(3) NOT NULL,
    "receivedAt" TIMESTAMP(3) NOT NULL,
    "processedAt" TIMESTAMP(3),
    "actorId" TEXT,
    "subject" TEXT,
    "body" TEXT,
    "participants" TEXT[],
    "labels" TEXT[],
    "metadata" JSONB NOT NULL,
    "status" "SourceEventStatus" NOT NULL DEFAULT 'RECEIVED',
    "fingerprint" TEXT NOT NULL,
    "lastError" TEXT,

    CONSTRAINT "SourceEvent_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "IngestionReviewItem" (
    "id" TEXT NOT NULL,
    "sourceEventId" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "candidate" JSONB NOT NULL,
    "status" "IngestionReviewStatus" NOT NULL DEFAULT 'OPEN',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "reviewedAt" TIMESTAMP(3),
    "reviewedBy" TEXT,
    "resolution" TEXT,

    CONSTRAINT "IngestionReviewItem_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ConnectorAccount" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "kind" "ConnectorKind" NOT NULL,
    "externalAccountId" TEXT NOT NULL,
    "displayName" TEXT NOT NULL,
    "status" "ConnectorStatus" NOT NULL DEFAULT 'DISCONNECTED',
    "scopes" TEXT[],
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "lastSuccessfulSyncAt" TIMESTAMP(3),
    "lastError" TEXT,

    CONSTRAINT "ConnectorAccount_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SyncCheckpoint" (
    "id" TEXT NOT NULL,
    "connectorAccountId" TEXT NOT NULL,
    "cursor" TEXT,
    "historyId" TEXT,
    "syncToken" TEXT,
    "expiresAt" TIMESTAMP(3),
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "SyncCheckpoint_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "OAuthState" (
    "state" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "kind" "ConnectorKind" NOT NULL,
    "redirectUri" TEXT NOT NULL,
    "requestedScopes" TEXT[],
    "createdBy" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "consumedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "OAuthState_pkey" PRIMARY KEY ("state")
);

-- CreateTable
CREATE TABLE "WebhookSubscription" (
    "id" TEXT NOT NULL,
    "connectorAccountId" TEXT NOT NULL,
    "externalChannelId" TEXT NOT NULL,
    "secret" TEXT NOT NULL,
    "status" "WebhookSubscriptionStatus" NOT NULL DEFAULT 'ACTIVE',
    "expiresAt" TIMESTAMP(3),
    "lastNotificationAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "WebhookSubscription_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "IdempotencyRecord" (
    "id" TEXT NOT NULL,
    "scope" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "requestHash" TEXT NOT NULL,
    "responseStatus" INTEGER,
    "responseBody" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "completedAt" TIMESTAMP(3),

    CONSTRAINT "IdempotencyRecord_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ConnectorOperationalSnapshot" (
    "id" TEXT NOT NULL,
    "connectorId" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "lastSuccessfulSyncAt" TIMESTAMP(3),
    "lastAttemptAt" TIMESTAMP(3),
    "consecutiveFailures" INTEGER NOT NULL DEFAULT 0,
    "pendingRetries" INTEGER NOT NULL DEFAULT 0,
    "deadLetterCount" INTEGER NOT NULL DEFAULT 0,
    "reauthRequired" BOOLEAN NOT NULL DEFAULT false,
    "rateLimitedUntil" TIMESTAMP(3),
    "lastErrorCode" TEXT,
    "lastErrorMessage" TEXT,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ConnectorOperationalSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "IntegrationIncident" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "connectorId" TEXT,
    "severity" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "firstObservedAt" TIMESTAMP(3) NOT NULL,
    "lastObservedAt" TIMESTAMP(3) NOT NULL,
    "occurrenceCount" INTEGER NOT NULL DEFAULT 1,
    "assignedTo" TEXT,
    "resolutionNote" TEXT,
    "resolvedAt" TIMESTAMP(3),

    CONSTRAINT "IntegrationIncident_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ConnectorRetryCommand" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "connectorId" TEXT NOT NULL,
    "operation" TEXT NOT NULL,
    "payload" JSONB NOT NULL,
    "attempt" INTEGER NOT NULL DEFAULT 0,
    "maxAttempts" INTEGER NOT NULL DEFAULT 5,
    "nextAttemptAt" TIMESTAMP(3) NOT NULL,
    "status" TEXT NOT NULL,
    "lastError" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ConnectorRetryCommand_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ConnectorDeadLetterItem" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "connectorId" TEXT NOT NULL,
    "operation" TEXT NOT NULL,
    "payload" JSONB NOT NULL,
    "totalAttempts" INTEGER NOT NULL,
    "lastError" TEXT NOT NULL,
    "failedAt" TIMESTAMP(3) NOT NULL,
    "acknowledgedAt" TIMESTAMP(3),
    "acknowledgedBy" TEXT,
    "resolution" TEXT,

    CONSTRAINT "ConnectorDeadLetterItem_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ItepTask_organizationId_status_idx" ON "ItepTask"("organizationId", "status");

-- CreateIndex
CREATE INDEX "ItepTask_assigneeId_status_idx" ON "ItepTask"("assigneeId", "status");

-- CreateIndex
CREATE INDEX "ItepTask_priority_nextCheckAt_idx" ON "ItepTask"("priority", "nextCheckAt");

-- CreateIndex
CREATE INDEX "ItepTask_dueAt_status_idx" ON "ItepTask"("dueAt", "status");

-- CreateIndex
CREATE INDEX "ItepTask_semanticFingerprint_status_idx" ON "ItepTask"("semanticFingerprint", "status");

-- CreateIndex
CREATE UNIQUE INDEX "ItepTask_organizationId_source_sourceExternalId_key" ON "ItepTask"("organizationId", "source", "sourceExternalId");

-- CreateIndex
CREATE INDEX "TaskEvidence_taskId_submittedAt_idx" ON "TaskEvidence"("taskId", "submittedAt");

-- CreateIndex
CREATE INDEX "TaskAuditEvent_taskId_occurredAt_idx" ON "TaskAuditEvent"("taskId", "occurredAt");

-- CreateIndex
CREATE UNIQUE INDEX "TaskAuditEvent_taskId_sequence_key" ON "TaskAuditEvent"("taskId", "sequence");

-- CreateIndex
CREATE UNIQUE INDEX "NotificationOutbox_idempotencyKey_key" ON "NotificationOutbox"("idempotencyKey");

-- CreateIndex
CREATE INDEX "NotificationOutbox_sentAt_scheduledFor_idx" ON "NotificationOutbox"("sentAt", "scheduledFor");

-- CreateIndex
CREATE UNIQUE INDEX "TaskDependency_taskId_dependsOnId_key" ON "TaskDependency"("taskId", "dependsOnId");

-- CreateIndex
CREATE INDEX "HumanAnneIncident_status_severity_createdAt_idx" ON "HumanAnneIncident"("status", "severity", "createdAt");

-- CreateIndex
CREATE INDEX "HumanAnneIncident_taskId_idx" ON "HumanAnneIncident"("taskId");

-- CreateIndex
CREATE UNIQUE INDEX "SourceEvent_fingerprint_key" ON "SourceEvent"("fingerprint");

-- CreateIndex
CREATE INDEX "SourceEvent_organizationId_status_occurredAt_idx" ON "SourceEvent"("organizationId", "status", "occurredAt");

-- CreateIndex
CREATE UNIQUE INDEX "SourceEvent_organizationId_source_externalId_key" ON "SourceEvent"("organizationId", "source", "externalId");

-- CreateIndex
CREATE INDEX "IngestionReviewItem_organizationId_status_createdAt_idx" ON "IngestionReviewItem"("organizationId", "status", "createdAt");

-- CreateIndex
CREATE INDEX "ConnectorAccount_organizationId_status_idx" ON "ConnectorAccount"("organizationId", "status");

-- CreateIndex
CREATE UNIQUE INDEX "ConnectorAccount_organizationId_kind_externalAccountId_key" ON "ConnectorAccount"("organizationId", "kind", "externalAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "SyncCheckpoint_connectorAccountId_key" ON "SyncCheckpoint"("connectorAccountId");

-- CreateIndex
CREATE INDEX "OAuthState_expiresAt_consumedAt_idx" ON "OAuthState"("expiresAt", "consumedAt");

-- CreateIndex
CREATE UNIQUE INDEX "WebhookSubscription_externalChannelId_key" ON "WebhookSubscription"("externalChannelId");

-- CreateIndex
CREATE INDEX "WebhookSubscription_connectorAccountId_status_idx" ON "WebhookSubscription"("connectorAccountId", "status");

-- CreateIndex
CREATE INDEX "IdempotencyRecord_expiresAt_idx" ON "IdempotencyRecord"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "IdempotencyRecord_scope_key_key" ON "IdempotencyRecord"("scope", "key");

-- CreateIndex
CREATE INDEX "ConnectorOperationalSnapshot_organizationId_status_idx" ON "ConnectorOperationalSnapshot"("organizationId", "status");

-- CreateIndex
CREATE UNIQUE INDEX "ConnectorOperationalSnapshot_organizationId_connectorId_key" ON "ConnectorOperationalSnapshot"("organizationId", "connectorId");

-- CreateIndex
CREATE INDEX "IntegrationIncident_organizationId_status_severity_idx" ON "IntegrationIncident"("organizationId", "status", "severity");

-- CreateIndex
CREATE INDEX "IntegrationIncident_connectorId_status_idx" ON "IntegrationIncident"("connectorId", "status");

-- CreateIndex
CREATE INDEX "ConnectorRetryCommand_status_nextAttemptAt_idx" ON "ConnectorRetryCommand"("status", "nextAttemptAt");

-- CreateIndex
CREATE INDEX "ConnectorRetryCommand_organizationId_connectorId_idx" ON "ConnectorRetryCommand"("organizationId", "connectorId");

-- CreateIndex
CREATE INDEX "ConnectorDeadLetterItem_organizationId_acknowledgedAt_idx" ON "ConnectorDeadLetterItem"("organizationId", "acknowledgedAt");

-- CreateIndex
CREATE INDEX "ConnectorDeadLetterItem_connectorId_failedAt_idx" ON "ConnectorDeadLetterItem"("connectorId", "failedAt");

-- AddForeignKey
ALTER TABLE "TaskEvidence" ADD CONSTRAINT "TaskEvidence_taskId_fkey" FOREIGN KEY ("taskId") REFERENCES "ItepTask"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TaskAuditEvent" ADD CONSTRAINT "TaskAuditEvent_taskId_fkey" FOREIGN KEY ("taskId") REFERENCES "ItepTask"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "NotificationOutbox" ADD CONSTRAINT "NotificationOutbox_taskId_fkey" FOREIGN KEY ("taskId") REFERENCES "ItepTask"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TaskDependency" ADD CONSTRAINT "TaskDependency_taskId_fkey" FOREIGN KEY ("taskId") REFERENCES "ItepTask"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TaskDependency" ADD CONSTRAINT "TaskDependency_dependsOnId_fkey" FOREIGN KEY ("dependsOnId") REFERENCES "ItepTask"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "IngestionReviewItem" ADD CONSTRAINT "IngestionReviewItem_sourceEventId_fkey" FOREIGN KEY ("sourceEventId") REFERENCES "SourceEvent"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SyncCheckpoint" ADD CONSTRAINT "SyncCheckpoint_connectorAccountId_fkey" FOREIGN KEY ("connectorAccountId") REFERENCES "ConnectorAccount"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "WebhookSubscription" ADD CONSTRAINT "WebhookSubscription_connectorAccountId_fkey" FOREIGN KEY ("connectorAccountId") REFERENCES "ConnectorAccount"("id") ON DELETE CASCADE ON UPDATE CASCADE;
