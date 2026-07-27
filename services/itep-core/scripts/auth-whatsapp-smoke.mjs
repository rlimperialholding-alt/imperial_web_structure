import { createHmac } from "node:crypto";
import { totpCode } from "../dist/src/security/totp.js";

const baseUrl = process.env.SMOKE_API_BASE_URL ?? "http://127.0.0.1:3311";
const bootstrapToken =
  process.env.AUTH_BOOTSTRAP_TOKEN ??
  "smoke-auth-bootstrap-token-000000000001";
const verifyToken =
  process.env.WHATSAPP_VERIFY_TOKEN ?? "smoke-whatsapp-verify-token";
const appSecret =
  process.env.WHATSAPP_APP_SECRET ??
  "smoke-whatsapp-app-secret-000000000001";
const adminPassword = "Hosszú zöld kapu próbamondat 2026!";
const customerPassword = "Kék épület biztonságos próbamondat 2026!";

const enrollment = await request("/v1/auth/bootstrap", {
  method: "POST",
  headers: { "x-bootstrap-token": bootstrapToken },
  body: {
    email: "admin@imperial.test",
    displayName: "Imperial Test Admin",
    password: adminPassword,
    organizationId: "imperial-holding",
    organizationName: "Imperial Holding Test",
  },
});
const adminSession = await request("/v1/auth/mfa/enroll/confirm", {
  method: "POST",
  body: {
    enrollmentToken: enrollment.enrollmentToken,
    code: totpCode(enrollment.secret),
  },
});
assert(adminSession.recoveryCodes.length === 10, "admin recovery codes");

const adminHeaders = {
  authorization: `Bearer ${adminSession.sessionToken}`,
};
const me = await request("/v1/auth/me", { headers: adminHeaders });
assert(me.isSystemAdmin === true, "bootstrap admin access");
assert(me.activePermissions.includes("*"), "bootstrap full permissions");

const invitation = await request("/v1/admin/users/invite", {
  method: "POST",
  headers: adminHeaders,
  body: {
    email: "customer@imperial.test",
    displayName: "Teszt Ügyfél",
    memberships: [{
      organizationId: "imperial-holding",
      jobRole: "CUSTOMER",
      projectIds: ["project-customer"],
      permissionGrants: [],
      permissionDenials: [],
    }],
  },
});
const customerEnrollment = await request("/v1/auth/invitations/accept", {
  method: "POST",
  body: {
    invitationToken: invitation.invitationToken,
    password: customerPassword,
  },
});
const customerSession = await request("/v1/auth/mfa/enroll/confirm", {
  method: "POST",
  body: {
    enrollmentToken: customerEnrollment.enrollmentToken,
    code: totpCode(customerEnrollment.secret),
  },
});
const customerHeaders = {
  authorization: `Bearer ${customerSession.sessionToken}`,
};

const challenge = await fetch(
  `${baseUrl}/v1/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=${encodeURIComponent(
    verifyToken,
  )}&hub.challenge=smoke-ok`,
);
assert(challenge.ok && (await challenge.text()) === "smoke-ok", "webhook challenge");

const webhookPayload = {
  object: "whatsapp_business_account",
  entry: [{
    changes: [{
      value: {
        metadata: { phone_number_id: "100000000001" },
        contacts: [{
          wa_id: "36301234567",
          profile: { name: "WhatsApp Teszt Ügyfél" },
        }],
        messages: [{
          id: "wamid.smoke-inbound-1",
          from: "36301234567",
          timestamp: String(Math.floor(Date.now() / 1000)),
          type: "text",
          text: { body: "Teszt bejövő üzenet" },
        }],
      },
    }],
  }],
};
const rawWebhook = JSON.stringify(webhookPayload);
const signature = `sha256=${createHmac("sha256", appSecret)
  .update(rawWebhook)
  .digest("hex")}`;
const webhook = await fetch(`${baseUrl}/v1/webhooks/whatsapp`, {
  method: "POST",
  headers: {
    "content-type": "application/json",
    "x-hub-signature-256": signature,
  },
  body: rawWebhook,
});
assert(webhook.ok, `signed webhook: ${await webhook.text()}`);

const adminConversations = await request("/v1/whatsapp/conversations", {
  headers: adminHeaders,
});
assert(adminConversations.length === 1, "admin sees inbound conversation");
const conversation = adminConversations[0];

const hiddenFromUnassignedCustomer = await request(
  "/v1/whatsapp/conversations",
  { headers: customerHeaders },
);
assert(
  hiddenFromUnassignedCustomer.length === 0,
  "empty project scope cannot see group conversations",
);

await request(`/v1/whatsapp/conversations/${conversation.id}`, {
  method: "PATCH",
  headers: adminHeaders,
  body: {
    crmCustomerId: "customer-smoke",
    projectId: "project-customer",
  },
});
const visibleToAssignedCustomer = await request(
  "/v1/whatsapp/conversations",
  { headers: customerHeaders },
);
assert(visibleToAssignedCustomer.length === 1, "assigned customer project scope");

const pending = await request(
  `/v1/whatsapp/conversations/${conversation.id}/messages`,
  {
    method: "POST",
    headers: customerHeaders,
    body: { body: "Jóváhagyásra váró válasz" },
  },
);
assert(pending.status === "PENDING_APPROVAL", "customer message approval gate");

const sent = await request(`/v1/whatsapp/messages/${pending.id}/approve`, {
  method: "POST",
  headers: adminHeaders,
});
assert(sent.status === "SENT", "approved message dispatch");

const loginChallenge = await request("/v1/auth/login", {
  method: "POST",
  body: {
    email: "admin@imperial.test",
    password: adminPassword,
  },
});
const relogin = await request("/v1/auth/mfa/verify", {
  method: "POST",
  body: {
    challengeToken: loginChallenge.challengeToken,
    code: totpCode(enrollment.secret),
  },
});
assert(Boolean(relogin.sessionToken), "password and MFA relogin");

console.log("Auth and WhatsApp smoke test passed.");

async function request(path, options = {}) {
  const headers = {
    accept: "application/json",
    ...(options.body ? { "content-type": "application/json" } : {}),
    ...(options.headers ?? {}),
  };
  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(`${options.method ?? "GET"} ${path}: ${response.status} ${text}`);
  }
  return payload;
}

function assert(condition, label) {
  if (!condition) throw new Error(`Smoke assertion failed: ${label}`);
}
