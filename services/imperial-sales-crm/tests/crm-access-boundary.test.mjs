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
    "app/api/crm/customers/route.ts",
    "app/api/crm/customers/[id]/route.ts",
    "app/api/crm/contracts/route.ts",
    "app/api/crm/contracts/[id]/route.ts",
    "app/api/crm/projects/route.ts",
    "app/api/intelligence/route.ts",
    "app/api/intelligence/reviews/[id]/route.ts",
  ];
  for (const file of files) {
    const source = await readFile(file, "utf8");
    assert.match(source, /requireInternalCrmIdentity/);
    assert.doesNotMatch(source, /requireCrmIdentity\(request\)/);
  }
});

test("signed contracts atomically create a project and MyImperial customer membership", async () => {
  const source = await readFile("app/api/crm/contracts/[id]/route.ts", "utf8");
  assert.match(source, /db\.batch/);
  assert.match(source, /db\.insert\(projects\)/);
  assert.match(source, /db\.insert\(projectMembers\)/);
  assert.match(source, /contract\.signed_project\.created/);
  assert.match(source, /identity\.role === "sales"/);
});

test("imported customers are backfilled without inventing verified billing data", async () => {
  const migration = await readFile("drizzle/0010_backfill_canonical_customers.sql", "utf8");
  assert.match(migration, /crm_customer_imports/);
  assert.match(migration, /Adatpótlás szükséges/);
  assert.match(migration, /'prospect'/);
  assert.match(migration, /INSERT OR IGNORE/);
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
  assert.match(source, /dataState === "forbidden"/);
  assert.match(source, /dataState === "unavailable"/);
  assert.doesNotMatch(source, /dataState === "demo"/);
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

test("production CRM and MyImperial data are never auto-created as fixtures", async () => {
  const crmSeed = await readFile("lib/crm-seed.ts", "utf8");
  const portalSeed = await readFile("lib/myimperial-seed.ts", "utf8");
  assert.match(crmSeed, /CRM_DEMO_SEED_ENABLED !== "true"/);
  assert.match(portalSeed, /CRM_DEMO_SEED_ENABLED !== "true"/);
});

test("MyImperial resolves real project memberships instead of a hardcoded pilot", async () => {
  const auth = await readFile("lib/myimperial-auth.ts", "utf8");
  const route = await readFile("app/api/myimperial/route.ts", "utf8");
  const page = await readFile("app/myimperial/page.tsx", "utf8");
  assert.doesNotMatch(auth, /PILOT_PROJECT_ID/);
  assert.match(auth, /projectMembers\.email/);
  assert.match(auth, /x-imperial-project-id/);
  assert.match(route, /availableProjects/);
  assert.match(page, /Projekt kiválasztása/);
});
