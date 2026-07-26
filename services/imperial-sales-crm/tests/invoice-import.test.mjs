import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("invoice import is bounded at 250, source-idempotent and amount-safe", async () => {
  const source = await readFile("lib/invoice-import.ts", "utf8");
  assert.match(source, /MAX_INVOICES_PER_BATCH = 250/);
  assert.match(source, /payloadSha256/);
  assert.match(source, /sourceSha256/);
  assert.match(source, /netAmount \+ taxAmount !== grossAmount/);
  assert.match(source, /already exists with different data/);
  assert.match(source, /optionalText\(item\.description, 1000\)/);
  assert.match(source, /Számladokumentum/);
});

test("invoice storage links only verified customers and optional projects", async () => {
  const migration = await readFile(
    "drizzle/0007_finance_invoice_imports.sql",
    "utf8",
  );
  assert.match(migration, /finance_invoice_imports_source_idx/);
  assert.match(migration, /CREATE UNIQUE INDEX/);
  assert.match(
    migration,
    /FOREIGN KEY \(`customer_import_id`\) REFERENCES `crm_customer_imports`/,
  );
  assert.match(migration, /FOREIGN KEY \(`project_id`\) REFERENCES `projects`/);
});

test("invoice import links only an unambiguous normalized buyer match", async () => {
  const source = await readFile("lib/invoice-import.ts", "utf8");
  assert.match(source, /invoice\.customerSourceSystem/);
  assert.match(source, /invoice\.customerExternalId/);
  assert.match(source, /normalizedCustomerName/);
  assert.match(source, /uniqueCandidates\.length === 1/);
  assert.match(source, /customerMatchStatus/);
});

test("storno invoices require a reference and negative amount", async () => {
  const source = await readFile("lib/invoice-import.ts", "utf8");
  assert.match(source, /storno.*grossAmount >= 0/);
  assert.match(source, /storno invoice needs referencedInvoiceNumber/);
});

test("invoice migration route uses the write-only migration token", async () => {
  const route = await readFile(
    "app/api/integrations/migration/invoices/import/route.ts",
    "utf8",
  );
  assert.match(route, /CRM_MIGRATION_TOKEN/);
  assert.match(route, /X-CRM-Migration-Token/);
  assert.doesNotMatch(route, /ITEP_CRM_READ_TOKEN/);
});
