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
  assert.doesNotMatch(source, /location\.hostname === "localhost"/);
});

test("the CRM trusts the internal session service instead of browser identity headers", async () => {
  const auth = await readFile("lib/crm-auth.ts", "utf8");
  const proxy = await readFile("lib/itep-auth.ts", "utf8");
  assert.match(auth, /verifyInternalUser/);
  assert.doesNotMatch(auth, /oai-authenticated-user-email/);
  assert.match(proxy, /\/v1\/auth\/csrf\/verify/);
  assert.match(proxy, /x-csrf-token/);
  assert.match(proxy, /cache: "no-store"/);
});

test("the browser exposes MFA enrollment, recovery and administrator access management", async () => {
  const login = await readFile("app/login/page.tsx", "utf8");
  const admin = await readFile("app/admin/access/page.tsx", "utf8");
  assert.match(login, /mfa\/verify/);
  assert.match(login, /mfa\/enroll\/confirm/);
  assert.match(login, /recoveryCodes/);
  assert.match(admin, /job-role-templates/);
  assert.match(admin, /users\/\$\{selected\.id\}\/access/);
  assert.match(admin, /users\/\$\{selected\.id\}\/recovery/);
});

test("WhatsApp conversations only use the authenticated server proxy", async () => {
  const page = await readFile("app/communications/whatsapp/page.tsx", "utf8");
  const proxy = await readFile("app/api/whatsapp/[...path]/route.ts", "utf8");
  assert.match(page, /authenticatedFetch/);
  assert.match(page, /PENDING_APPROVAL/);
  assert.match(proxy, /proxyIdentityResponse/);
  assert.doesNotMatch(page, /graph\.facebook\.com/);
});
