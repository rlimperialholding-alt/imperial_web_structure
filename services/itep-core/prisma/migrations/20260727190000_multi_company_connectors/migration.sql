-- Multi-company connector ownership and legal-entity registry.
CREATE TYPE "ConnectorScope" AS ENUM ('GROUP', 'LEGAL_ENTITY');
CREATE TYPE "LegalEntityStatus" AS ENUM ('ACTIVE', 'INACTIVE');

ALTER TYPE "ConnectorKind" ADD VALUE 'GOVERNMENT_PORTAL';

CREATE TABLE "LegalEntity" (
    "id" TEXT NOT NULL,
    "organizationId" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "legalName" TEXT NOT NULL,
    "taxNumber" TEXT,
    "status" "LegalEntityStatus" NOT NULL DEFAULT 'ACTIVE',
    "metadata" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "LegalEntity_pkey" PRIMARY KEY ("id")
);

ALTER TABLE "ConnectorAccount"
    ADD COLUMN "scope" "ConnectorScope" NOT NULL DEFAULT 'GROUP',
    ADD COLUMN "scopeKey" TEXT NOT NULL DEFAULT 'GROUP',
    ADD COLUMN "legalEntityId" TEXT,
    ADD COLUMN "configuration" JSONB;

ALTER TABLE "ItepTask" ADD COLUMN "legalEntityId" TEXT;
ALTER TABLE "SourceEvent" ADD COLUMN "legalEntityId" TEXT;

-- A financial connector must not continue syncing until its owning company is
-- explicitly selected. This avoids cross-company invoice or bank attribution.
UPDATE "ConnectorAccount"
SET
    "status" = 'DISCONNECTED',
    "lastError" = 'Legal entity assignment is required before synchronization'
WHERE "kind" IN ('BILLINGO', 'BANK')
  AND "status" IN ('ACTIVE', 'DEGRADED');

DROP INDEX "ConnectorAccount_organizationId_kind_externalAccountId_key";

CREATE UNIQUE INDEX "LegalEntity_organizationId_slug_key"
    ON "LegalEntity"("organizationId", "slug");
CREATE INDEX "LegalEntity_organizationId_status_idx"
    ON "LegalEntity"("organizationId", "status");
CREATE UNIQUE INDEX "ConnectorAccount_organizationId_kind_scopeKey_externalAccountId_key"
    ON "ConnectorAccount"("organizationId", "kind", "scopeKey", "externalAccountId");
CREATE INDEX "ConnectorAccount_legalEntityId_kind_status_idx"
    ON "ConnectorAccount"("legalEntityId", "kind", "status");
CREATE INDEX "ItepTask_legalEntityId_status_idx"
    ON "ItepTask"("legalEntityId", "status");
CREATE INDEX "SourceEvent_legalEntityId_status_occurredAt_idx"
    ON "SourceEvent"("legalEntityId", "status", "occurredAt");

ALTER TABLE "ConnectorAccount"
    ADD CONSTRAINT "ConnectorAccount_legalEntityId_fkey"
    FOREIGN KEY ("legalEntityId") REFERENCES "LegalEntity"("id")
    ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "ItepTask"
    ADD CONSTRAINT "ItepTask_legalEntityId_fkey"
    FOREIGN KEY ("legalEntityId") REFERENCES "LegalEntity"("id")
    ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "SourceEvent"
    ADD CONSTRAINT "SourceEvent_legalEntityId_fkey"
    FOREIGN KEY ("legalEntityId") REFERENCES "LegalEntity"("id")
    ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "ConnectorAccount"
    ADD CONSTRAINT "ConnectorAccount_scope_consistency_check"
    CHECK (
        ("scope" = 'GROUP' AND "legalEntityId" IS NULL AND "scopeKey" = 'GROUP')
        OR
        ("scope" = 'LEGAL_ENTITY' AND "legalEntityId" IS NOT NULL AND "scopeKey" = "legalEntityId")
    );
