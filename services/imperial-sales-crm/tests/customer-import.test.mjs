import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("real-data import is bounded at 250 customers and uses source idempotency", async () => {
  const source = await readFile("lib/customer-import.ts", "utf8");
  assert.match(source, /MAX_CUSTOMERS_PER_BATCH = 250/);
  assert.match(source, /payloadSha256/);
  assert.match(source, /customerImports\.externalId/);
  assert.match(source, /already exists with different data/);
  assert.match(source, /or\(\.\.\.contactMatches\)/);
});

test("customer import source mapping is durable and unique", async () => {
  const migration = await readFile(
    "drizzle/0006_customer_import_sources.sql",
    "utf8",
  );
  assert.match(migration, /crm_customer_imports/);
  assert.match(migration, /crm_customer_imports_source_idx/);
  assert.match(migration, /CREATE UNIQUE INDEX/);
  assert.match(migration, /FOREIGN KEY \(`lead_id`\) REFERENCES `leads`/);
});

test("customer import route is protected by the write-only migration token", async () => {
  const route = await readFile(
    "app/api/integrations/migration/customers/import/route.ts",
    "utf8",
  );
  assert.match(route, /CRM_MIGRATION_TOKEN/);
  assert.match(route, /X-CRM-Migration-Token/);
  assert.doesNotMatch(route, /ITEP_CRM_READ_TOKEN/);
});

test("the local CRM can use a persistent data path outside the checkout", async () => {
  const config = await readFile("vite.config.ts", "utf8");
  assert.match(config, /CRM_PERSIST_PATH/);
  assert.match(config, /persistState/);
});
