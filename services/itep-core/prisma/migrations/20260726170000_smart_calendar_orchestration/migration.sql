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

CREATE UNIQUE INDEX "OrchestrationEvent_organizationId_source_externalEventId_key"
    ON "OrchestrationEvent"("organizationId", "source", "externalEventId");
CREATE INDEX "OrchestrationEvent_organizationId_status_occurredAt_idx"
    ON "OrchestrationEvent"("organizationId", "status", "occurredAt");
CREATE INDEX "OrchestrationEvent_projectId_occurredAt_idx"
    ON "OrchestrationEvent"("projectId", "occurredAt");
