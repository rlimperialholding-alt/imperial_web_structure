import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("every internal CRM endpoint uses the internal-only identity guard", async () => {
  const files = [
    "app/api/crm/route.ts",
    "app/api/crm/leads/route.ts",
    "app/api/crm/leads/[id]/route.ts",
    "app/api/crm/tasks/route.ts",
    "app/api/crm/tasks/[id]/route.ts",
    "app/api/intelligence/route.ts",
    "app/api/intelligence/reviews/[id]/route.ts",
  ];
  for (const file of files) {
    const source = await readFile(file, "utf8");
    assert.match(source, /requireInternalCrmIdentity/);
    assert.doesNotMatch(source, /requireCrmIdentity\(request\)/);
  }
});

test("the formerly placeholder Intelligence navigation opens persisted workspaces", async () => {
  const source = await readFile("app/page.tsx", "utf8");
  assert.match(source, /changeView\("projects"\)/);
  assert.match(source, /changeView\("calendar"\)/);
  assert.match(source, /changeView\("knowledge"\)/);
  assert.match(source, /changeView\("agents"\)/);
  assert.match(source, /changeView\("audit"\)/);
  assert.doesNotMatch(source, /Projektek modul a következő fejlesztési ütemben/);
  assert.doesNotMatch(source, /tudásbázis csatlakoztatása előkészítés alatt/);
});

test("import review decisions are restricted, persisted and audited", async () => {
  const source = await readFile("app/api/intelligence/reviews/[id]/route.ts", "utf8");
  assert.match(source, /requireInternalCrmIdentity/);
  assert.match(source, /importReviewItems/);
  assert.match(source, /activities/);
  assert.match(source, /IMPORT_REVIEW_RESOLVED/);
});

test("customer and contact memberships are denied from internal CRM data", async () => {
  const source = await readFile("lib/crm-auth.ts", "utf8");
  assert.match(source, /\["customer", "contact"\]/);
  assert.match(source, /belső CRM csak Imperial munkatársak/);
});

test("the CRM does not server-render fallback lead data before authorization", async () => {
  const source = await readFile("app/page.tsx", "utf8");
  assert.match(source, /useState<Lead\[\]>\(\[\]\)/);
  assert.match(source, /useState<Task\[\]>\(\[\]\)/);
  assert.match(source, /dataState === "error"/);
});
