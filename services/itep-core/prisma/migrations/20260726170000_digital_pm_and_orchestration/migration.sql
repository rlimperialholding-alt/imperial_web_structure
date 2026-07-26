CREATE TYPE "DigitalManagerStatus" AS ENUM ('ACTIVE', 'PAUSED');

CREATE TABLE "DigitalProjectManager" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "displayName" TEXT NOT NULL,
    "roleName" TEXT NOT NULL,
    "status" "DigitalManagerStatus" NOT NULL DEFAULT 'ACTIVE',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "DigitalProjectManager_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "DigitalProjectAssignment" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "managerId" TEXT NOT NULL,
    "assignedBy" TEXT NOT NULL,
    "assignedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "DigitalProjectAssignment_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "DigitalPmAuditEvent" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "actorId" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "projectId" TEXT,
    "managerId" TEXT,
    "actionRisk" TEXT,
    "decision" TEXT,
    "payload" JSONB NOT NULL,
    "occurredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "DigitalPmAuditEvent_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "OrchestrationEvent" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "source" TEXT NOT NULL,
    "externalEventId" TEXT NOT NULL,
    "eventType" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "ownerId" TEXT NOT NULL,
    "status" TEXT NOT NULL,
    "payload" JSONB NOT NULL,
    "taskIds" TEXT[],
    "occurredAt" TIMESTAMP(3) NOT NULL,
    "receivedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "processedAt" TIMESTAMP(3),
    "lastError" TEXT,
    CONSTRAINT "OrchestrationEvent_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "DigitalProjectManager_organizationId_displayName_key"
    ON "DigitalProjectManager"("organizationId", "displayName");
CREATE INDEX "DigitalProjectManager_organizationId_status_idx"
    ON "DigitalProjectManager"("organizationId", "status");
CREATE UNIQUE INDEX "DigitalProjectAssignment_organizationId_projectId_key"
    ON "DigitalProjectAssignment"("organizationId", "projectId");
CREATE INDEX "DigitalProjectAssignment_managerId_updatedAt_idx"
    ON "DigitalProjectAssignment"("managerId", "updatedAt");
CREATE INDEX "DigitalPmAuditEvent_organizationId_occurredAt_idx"
    ON "DigitalPmAuditEvent"("organizationId", "occurredAt");
CREATE INDEX "DigitalPmAuditEvent_projectId_occurredAt_idx"
    ON "DigitalPmAuditEvent"("projectId", "occurredAt");
CREATE UNIQUE INDEX "OrchestrationEvent_organizationId_source_externalEventId_key"
    ON "OrchestrationEvent"("organizationId", "source", "externalEventId");
CREATE INDEX "OrchestrationEvent_organizationId_status_occurredAt_idx"
    ON "OrchestrationEvent"("organizationId", "status", "occurredAt");
CREATE INDEX "OrchestrationEvent_projectId_occurredAt_idx"
    ON "OrchestrationEvent"("projectId", "occurredAt");

ALTER TABLE "DigitalProjectAssignment"
    ADD CONSTRAINT "DigitalProjectAssignment_managerId_fkey"
    FOREIGN KEY ("managerId") REFERENCES "DigitalProjectManager"("id")
    ON DELETE RESTRICT ON UPDATE CASCADE;
