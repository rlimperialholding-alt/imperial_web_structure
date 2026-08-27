import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createInvitationToken, invitationTokenHash } from "../lib/invitation-token.ts";

test("invitation tokens are high-entropy and only their deterministic hash is stored", async () => {
  const first = createInvitationToken();
  const second = createInvitationToken();
  assert.match(first, /^[a-f0-9]{64}$/);
  assert.notEqual(first, second);
  assert.equal(await invitationTokenHash(first), createHash("sha256").update(first).digest("hex"));
});

test("invitation acceptance is bound to the invited email and pending status", async () => {
  const source = await readFile("app/api/myimperial/invitations/accept/route.ts", "utf8");
  assert.match(source, /identity\.email !== invitation\.email/);
  assert.match(source, /projectInvitations\.status, "pending"/);
  assert.match(source, /invitation\.expiresAt/);
});

test("customer-level inviters cannot assign internal professional roles", async () => {
  const source = await readFile("app/api/myimperial/members/route.ts", "utf8");
  assert.match(source, /identity\.role !== "admin" && role !== "contact"/);
});
