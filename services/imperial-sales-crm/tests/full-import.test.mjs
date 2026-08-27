import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("live import stores Drive and Gmail sources as links only", async () => {
  const migration = await readFile(
    "drizzle/0008_live_source_registry.sql",
    "utf8",
  );
  assert.match(migration, /crm_source_records_source_idx/);
  assert.match(migration, /storage_mode/);
  assert.match(migration, /DEFAULT 'link'/);
  assert.doesNotMatch(migration, /object_key|file_bytes|blob/i);
});

test("live import keeps projects, partners, sources and review items durable", async () => {
  const migration = await readFile(
    "drizzle/0008_live_source_registry.sql",
    "utf8",
  );
  assert.match(migration, /crm_business_partners/);
  assert.match(migration, /crm_business_partner_sources/);
  assert.match(migration, /crm_business_projects/);
  assert.match(migration, /crm_import_review_items/);
  assert.match(migration, /FOREIGN KEY \(`source_record_id`\)/);
});

test("live import is bounded, idempotent and uses the write-only token", async () => {
  const [source, route] = await Promise.all([
    readFile("lib/full-import.ts", "utf8"),
    readFile(
      "app/api/integrations/migration/full/import/route.ts",
      "utf8",
    ),
  ]);
  assert.match(source, /MAX_ITEMS_PER_COLLECTION = 250/);
  assert.match(source, /changed without a new source version/);
  assert.match(source, /onConflictDoNothing/);
  assert.match(source, /storageMode: "link"/);
  assert.match(route, /CRM_MIGRATION_TOKEN/);
  assert.match(route, /X-CRM-Migration-Token/);
});

test("live source URLs are restricted to approved Google hosts", async () => {
  const source = await readFile("lib/full-import.ts", "utf8");
  assert.match(source, /drive\.google\.com/);
  assert.match(source, /docs\.google\.com/);
  assert.match(source, /mail\.google\.com/);
  assert.match(source, /sourceUrl must be an approved Google source/);
});

test("the authenticated CRM dashboard exposes import counts and source links", async () => {
  const [route, page] = await Promise.all([
    readFile("app/api/crm/route.ts", "utf8"),
    readFile("app/page.tsx", "utf8"),
  ]);
  assert.match(route, /getFullImportStatus/);
  assert.match(route, /CRM_WORKSPACE_ID/);
  assert.match(page, /Importált üzleti adatok/);
  assert.match(page, /Legutóbb nyilvántartott dokumentumok/);
  assert.match(page, /rel="noreferrer"/);
});
