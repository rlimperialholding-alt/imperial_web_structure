ALTER TYPE "ConnectorKind" ADD VALUE IF NOT EXISTS 'DRIVE';

CREATE TABLE IF NOT EXISTS "ConnectorOperationalSnapshot" (
  "id" TEXT NOT NULL, "connectorId" TEXT NOT NULL, "organizationId" TEXT NOT NULL,
  "kind" TEXT NOT NULL, "status" TEXT NOT NULL, "lastSuccessfulSyncAt" TIMESTAMP(3),
  "lastAttemptAt" TIMESTAMP(3), "consecutiveFailures" INTEGER NOT NULL DEFAULT 0,
  "pendingRetries" INTEGER NOT NULL DEFAULT 0, "deadLetterCount" INTEGER NOT NULL DEFAULT 0,
  "reauthRequired" BOOLEAN NOT NULL DEFAULT false, "rateLimitedUntil" TIMESTAMP(3),
  "lastErrorCode" TEXT, "lastErrorMessage" TEXT, "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "ConnectorOperationalSnapshot_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "ConnectorOperationalSnapshot_organizationId_connectorId_key" ON "ConnectorOperationalSnapshot"("organizationId","connectorId");
CREATE INDEX IF NOT EXISTS "ConnectorOperationalSnapshot_organizationId_status_idx" ON "ConnectorOperationalSnapshot"("organizationId","status");

CREATE TABLE IF NOT EXISTS "IntegrationIncident" (
  "id" TEXT NOT NULL, "organizationId" TEXT NOT NULL, "connectorId" TEXT,
  "severity" TEXT NOT NULL, "type" TEXT NOT NULL, "status" TEXT NOT NULL,
  "title" TEXT NOT NULL, "description" TEXT NOT NULL, "firstObservedAt" TIMESTAMP(3) NOT NULL,
  "lastObservedAt" TIMESTAMP(3) NOT NULL, "occurrenceCount" INTEGER NOT NULL DEFAULT 1,
  "assignedTo" TEXT, "resolutionNote" TEXT, "resolvedAt" TIMESTAMP(3),
  CONSTRAINT "IntegrationIncident_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "IntegrationIncident_organizationId_status_severity_idx" ON "IntegrationIncident"("organizationId","status","severity");
CREATE INDEX IF NOT EXISTS "IntegrationIncident_connectorId_status_idx" ON "IntegrationIncident"("connectorId","status");

CREATE TABLE IF NOT EXISTS "ConnectorRetryCommand" (
  "id" TEXT NOT NULL, "organizationId" TEXT NOT NULL, "connectorId" TEXT NOT NULL,
  "operation" TEXT NOT NULL, "payload" JSONB NOT NULL, "attempt" INTEGER NOT NULL DEFAULT 0,
  "maxAttempts" INTEGER NOT NULL DEFAULT 5, "nextAttemptAt" TIMESTAMP(3) NOT NULL,
  "status" TEXT NOT NULL, "lastError" TEXT, "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL, CONSTRAINT "ConnectorRetryCommand_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "ConnectorRetryCommand_status_nextAttemptAt_idx" ON "ConnectorRetryCommand"("status","nextAttemptAt");
CREATE INDEX IF NOT EXISTS "ConnectorRetryCommand_organizationId_connectorId_idx" ON "ConnectorRetryCommand"("organizationId","connectorId");

CREATE TABLE IF NOT EXISTS "ConnectorDeadLetterItem" (
  "id" TEXT NOT NULL, "organizationId" TEXT NOT NULL, "connectorId" TEXT NOT NULL,
  "operation" TEXT NOT NULL, "payload" JSONB NOT NULL, "totalAttempts" INTEGER NOT NULL,
  "lastError" TEXT NOT NULL, "failedAt" TIMESTAMP(3) NOT NULL, "acknowledgedAt" TIMESTAMP(3),
  "acknowledgedBy" TEXT, "resolution" TEXT,
  CONSTRAINT "ConnectorDeadLetterItem_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "ConnectorDeadLetterItem_organizationId_acknowledgedAt_idx" ON "ConnectorDeadLetterItem"("organizationId","acknowledgedAt");
CREATE INDEX IF NOT EXISTS "ConnectorDeadLetterItem_connectorId_failedAt_idx" ON "ConnectorDeadLetterItem"("connectorId","failedAt");
