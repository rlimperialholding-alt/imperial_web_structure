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
  ];
  for (const file of files) {
    const source = await readFile(file, "utf8");
    assert.match(source, /requireInternalCrmIdentity/);
    assert.doesNotMatch(source, /requireCrmIdentity\(request\)/);
  }
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
