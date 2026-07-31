import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("the Sites artifact contains the worker, bindings and all migrations", async () => {
  const [
    hosting,
    crmMigration,
    portalMigration,
    documentMigration,
    invitationMigration,
    notificationMigration,
    itepMigration,
    liveSourceMigration,
    businessWorkflowMigration,
    customerBackfillMigration,
    cashflowMigration,
    milestoneMigration,
    projectWorkspaceMigration,
    fieldProcurementMigration,
    server,
  ] = await Promise.all([
    readFile("dist/.openai/hosting.json", "utf8"),
    readFile("dist/.openai/drizzle/0000_crm_core.sql", "utf8"),
    readFile("dist/.openai/drizzle/0001_myimperial_core.sql", "utf8"),
    readFile("dist/.openai/drizzle/0002_myimperial_documents.sql", "utf8"),
    readFile("dist/.openai/drizzle/0003_myimperial_invitations.sql", "utf8"),
    readFile("dist/.openai/drizzle/0004_myimperial_notifications.sql", "utf8"),
    readFile("dist/.openai/drizzle/0005_itep_migration_contract.sql", "utf8"),
    readFile("dist/.openai/drizzle/0008_live_source_registry.sql", "utf8"),
    readFile("dist/.openai/drizzle/0009_customer_contract_project.sql", "utf8"),
    readFile("dist/.openai/drizzle/0010_backfill_canonical_customers.sql", "utf8"),
    readFile("dist/.openai/drizzle/0011_cashflow_ledger.sql", "utf8"),
    readFile("dist/.openai/drizzle/0012_contract_payment_milestones.sql", "utf8"),
    readFile("dist/.openai/drizzle/0013_internal_project_workspace.sql", "utf8"),
    readFile("dist/.openai/drizzle/0014_field_and_procurement.sql", "utf8"),
    readFile("dist/server/index.js", "utf8"),
  ]);
  assert.deepEqual(JSON.parse(hosting), {
    project_id: "appgprj_6a5c78eb7e2481918dcaf1b3d34648a9",
    d1: "DB",
    r2: "DOCUMENTS",
  });
  assert.match(crmMigration, /CREATE TABLE `leads`/);
  assert.match(portalMigration, /CREATE TABLE `project_changes`/);
  assert.match(portalMigration, /CREATE TABLE `warranty_cases`/);
  assert.match(documentMigration, /CREATE TABLE `project_document_versions`/);
  assert.match(invitationMigration, /CREATE TABLE `project_invitations`/);
  assert.match(notificationMigration, /CREATE TABLE `email_notifications`/);
  assert.match(notificationMigration, /CREATE TABLE `notification_preferences`/);
  assert.match(itepMigration, /CREATE TABLE `crm_migration_batches`/);
  assert.match(itepMigration, /CREATE TABLE `crm_migration_documents`/);
  assert.match(liveSourceMigration, /CREATE TABLE `crm_source_records`/);
  assert.match(businessWorkflowMigration, /CREATE TABLE `crm_customers`/);
  assert.match(businessWorkflowMigration, /CREATE TABLE `crm_contracts`/);
  assert.match(customerBackfillMigration, /INSERT OR IGNORE INTO `crm_customers`/);
  assert.match(cashflowMigration, /CREATE TABLE `finance_cashflow_entries`/);
  assert.match(milestoneMigration, /CREATE TABLE `crm_contract_payment_milestones`/);
  assert.match(projectWorkspaceMigration, /CREATE TABLE `project_comments`/);
  assert.match(fieldProcurementMigration, /CREATE TABLE `procurement_requests`/);
  assert.match(server, /crm_source_records/);
});

test("customer email templates never expose internal commercial controls", async () => {
  const source = await readFile("lib/email-templates.ts", "utf8");
  assert.doesNotMatch(source, /fedezet|internalControl|profitabilitás/i);
  assert.match(source, /MyImperial felületén rögzítsd/);
});

test("the customer ChangeControl view does not expose an internal margin percentage", async () => {
  const source = await readFile("app/myimperial/page.tsx", "utf8");
  assert.doesNotMatch(source, /FRISSÍTETT FEDEZET|35% alatt|35,8%|36,2%/);
  assert.match(source, /BELSŐ KONTROLL/);
  assert.match(source, /jóváhagyás nélkül nincs végrehajtás/i);
});

test("MyImperial fails closed instead of showing pilot data after an API error", async () => {
  const source = await readFile("app/myimperial/page.tsx", "utf8");
  assert.match(source, /setLiveData\("error"\)/);
  assert.match(source, /liveData !== "live"/);
  assert.match(source, /nem jelenítünk meg mintaadatokat/);
  assert.doesNotMatch(source, /setLiveData\("demo"\)/);
  assert.doesNotMatch(source, /PILOT \/ BEMUTATÓ/);
});
