import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("migration writes and ITEP reads use separate service credentials", async () => {
  const writeRoute = await readFile(
    "app/api/integrations/migration/import/route.ts",
    "utf8",
  );
  const readRoute = await readFile(
    "app/api/integrations/itep/activities/route.ts",
    "utf8",
  );
  assert.match(writeRoute, /CRM_MIGRATION_TOKEN/);
  assert.match(writeRoute, /X-CRM-Migration-Token/);
  assert.match(readRoute, /ITEP_CRM_READ_TOKEN/);
  assert.match(readRoute, /X-ITEP-Token/);
  assert.doesNotMatch(readRoute, /\bPOST\b|\bPUT\b|\bPATCH\b|\bDELETE\b/);
});

test("migrated files are persisted to R2 and indexed in D1", async () => {
  const source = await readFile("lib/migration-contract.ts", "utf8");
  assert.match(source, /bucket\.put/);
  assert.match(source, /db\.insert\(migrationDocuments\)/);
  assert.match(source, /payloadSha256/);
  assert.match(source, /onConflictDoNothing/);
});

test("migration tables enforce durable source idempotency", async () => {
  const migration = await readFile(
    "drizzle/0005_itep_migration_contract.sql",
    "utf8",
  );
  assert.match(migration, /crm_migration_batches/);
  assert.match(migration, /crm_migration_documents_source_idx/);
  assert.match(migration, /CREATE UNIQUE INDEX/);
});
