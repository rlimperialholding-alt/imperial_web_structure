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
  assert.match(server, /crm_source_records/);
});

test("customer email templates never expose internal commercial controls", async () => {
  const source = await readFile("lib/email-templates.ts", "utf8");
  assert.doesNotMatch(source, /fedezet|internalControl|profitabilitás/i);
  assert.doesNotMatch(source, /MyImperial/i);
  assert.match(source, /Biztonsági okból ne továbbítsa ezt az üzenetet/);
  assert.match(source, /IMPERIAL HOLDING/);
});

test("the customer ChangeControl view does not expose an internal margin percentage", async () => {
  const source = await readFile("app/myimperial/page.tsx", "utf8");
  assert.doesNotMatch(source, /FRISSÍTETT FEDEZET|35% alatt|35,8%|36,2%/);
  assert.match(source, /BELSŐ KONTROLL/);
  assert.match(source, /jóváhagyás nélkül nincs végrehajtás/i);
});
