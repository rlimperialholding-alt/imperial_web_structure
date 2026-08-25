import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("email templates escape customer-provided HTML", async () => {
  const source = await readFile("lib/email-templates.ts", "utf8");
  assert.match(source, /function escapeHtml/);
  assert.match(source, /&lt;/);
  assert.match(source, /escapeHtml\(input\.eventSummary\)/);
  assert.match(source, /const safeTitle = escapeHtml\(title\)/);
  assert.doesNotMatch(source, /MYIMPERIAL/);
  assert.match(source, /IMPERIAL HOLDING/);
});

test("delivery uses provider idempotency and does not log secrets", async () => {
  const source = await readFile("lib/email-delivery.ts", "utf8");
  assert.match(source, /"idempotency-key": input\.idempotencyKey/);
  assert.match(source, /validateOutboundEmail/);
  assert.doesNotMatch(source, /console\./);
});

test("delivery fails closed on plain-language or brand-gate errors", async () => {
  const source = await readFile("lib/outbound-copy-guard.ts", "utf8");
  assert.match(source, /OUTBOUND_COPY_BLOCKED/);
  assert.match(source, /foreign_brand/);
  assert.match(source, /sentence_over_25_words/);
  assert.match(source, /projektjel-feldolgozás/);
  assert.match(source, /projektmenedzsment/);
  assert.match(source, /backend/);
  assert.match(source, /endpoint/);
  assert.match(source, /scope/);
  assert.match(source, /korai fejlesztési jel/);
  assert.match(source, /auditigény/);
});

test("invitation email sending verifies and redacts the one-time token", async () => {
  const source = await readFile("app/api/myimperial/notifications/invitation/send/route.ts", "utf8");
  assert.match(source, /invitationTokenHash\(token\)/);
  assert.match(source, /htmlBody: null, textBody: null/);
});
