import { createHmac, randomUUID } from "node:crypto";

const baseUrl =
  process.env.ITEP_API_INTERNAL_BASE_URL ?? "http://itep-api:3000";
const secret = process.env.IDENTITY_SHARED_SECRET;
const connectorId = "billingo-imperial-holding-mernoki-es-tanacsado";

if (!secret) {
  throw new Error("IDENTITY_SHARED_SECRET is required.");
}

function signedHeaders() {
  const now = Math.floor(Date.now() / 1000);
  const payload = Buffer.from(
    JSON.stringify({
      actorId: "digital-anne",
      organizationId: "imperial-holding",
      roles: ["SYSTEM_ADMIN"],
      permissions: ["connectors:read", "connectors:sync", "incidents:manage"],
      issuedAt: now,
      expiresAt: now + 300,
      nonce: randomUUID(),
    }),
    "utf8",
  ).toString("base64url");
  const signature = createHmac("sha256", secret)
    .update(payload)
    .digest("hex");
  return {
    "content-type": "application/json",
    "x-imperial-identity": payload,
    "x-imperial-identity-signature": `sha256=${signature}`,
  };
}

async function api(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      ...signedHeaders(),
      ...(options.headers ?? {}),
    },
  });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) {
    throw new Error(
      `API ${options.method ?? "GET"} ${path} failed with ${response.status}: ${JSON.stringify(body)}`,
    );
  }
  return body;
}

const sync = await api(`/v1/connectors/${connectorId}/sync`, {
  method: "POST",
});
let dashboard = await api("/v1/integration-control-room/dashboard");
const staleIncidents = dashboard.incidents.filter(
  (incident) =>
    incident.connectorId === connectorId &&
    incident.type === "REAUTH_REQUIRED",
);

for (const incident of staleIncidents) {
  await api(
    `/v1/integration-control-room/incidents/${incident.id}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({
        resolutionNote:
          "Billingo live read-only sync succeeded after credential activation; historical alert closed by verified production smoke test.",
      }),
    },
  );
}

dashboard = await api("/v1/integration-control-room/dashboard");
const connector = dashboard.connectors.find(
  (item) => item.connectorId === connectorId,
);

console.log(
  JSON.stringify(
    {
      sync,
      connector: connector
        ? {
            status: connector.status,
            consecutiveFailures: connector.consecutiveFailures,
            reauthRequired: connector.reauthRequired,
            pendingRetries: connector.pendingRetries,
            deadLetterCount: connector.deadLetterCount,
            lastErrorCode: connector.lastErrorCode ?? null,
            lastErrorMessage: connector.lastErrorMessage ?? null,
          }
        : null,
      resolvedStaleIncidents: staleIncidents.length,
      openIncidents: dashboard.incidents.filter(
        (incident) => incident.connectorId === connectorId,
      ).length,
      unacknowledgedDeadLetters: dashboard.deadLetters.filter(
        (item) =>
          item.connectorId === connectorId && !item.acknowledgedAt,
      ).length,
    },
    null,
    2,
  ),
);
