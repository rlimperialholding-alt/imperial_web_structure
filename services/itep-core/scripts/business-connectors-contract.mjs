import {
  BillingoApiGateway,
  GoogleAdsApiGateway,
  MetaAdsApiGateway,
} from "../dist/src/connectors/index.js";

if (process.env.READ_ONLY_MODE !== "true") {
  throw new Error("READ_ONLY_MODE=true is required; write operations are forbidden.");
}

const provider = (process.env.PROVIDER ?? "all").toLowerCase();
const results = [];

if (provider === "all" || provider === "billingo") {
  const gateway = new BillingoApiGateway(
    process.env.BILLINGO_API_BASE_URL ?? "https://api.billingo.hu",
  );
  const result = await gateway.listInvoiceChanges({
    accessToken: required("BILLINGO_API_KEY"),
    externalAccountId: process.env.BILLINGO_EXTERNAL_ACCOUNT_ID ?? "all",
  });
  results.push({
    provider: "billingo",
    mode: "read-only",
    received: result.invoices.length,
  });
}

if (provider === "all" || provider === "meta") {
  const gateway = new MetaAdsApiGateway(
    process.env.META_GRAPH_API_BASE_URL ?? "https://graph.facebook.com",
    process.env.META_GRAPH_API_VERSION ?? "v25.0",
  );
  const result = await gateway.listCampaignInsights({
    accessToken: required("META_ADS_ACCESS_TOKEN"),
    externalAccountId: required("META_ADS_AD_ACCOUNT_ID"),
  });
  results.push({
    provider: "meta",
    mode: "read-only",
    received: result.metrics.length,
  });
}

if (provider === "all" || provider === "google-ads") {
  const gateway = new GoogleAdsApiGateway(
    process.env.GOOGLE_ADS_API_BASE_URL ?? "https://googleads.googleapis.com",
    process.env.GOOGLE_ADS_API_VERSION ?? "v25",
    process.env.GOOGLE_OAUTH_TOKEN_URL ?? "https://oauth2.googleapis.com/token",
  );
  const serviceAccount = process.env.GOOGLE_ADS_SERVICE_ACCOUNT_JSON
    ? parseJsonObject(
        "GOOGLE_ADS_SERVICE_ACCOUNT_JSON",
        process.env.GOOGLE_ADS_SERVICE_ACCOUNT_JSON,
      )
    : undefined;
  const credentialEnvelope = {
    developerToken: required("GOOGLE_ADS_DEVELOPER_TOKEN"),
    ...(process.env.GOOGLE_ADS_ACCESS_TOKEN
      ? { accessToken: process.env.GOOGLE_ADS_ACCESS_TOKEN }
      : serviceAccount
        ? { serviceAccount }
      : {
          clientId: required("GOOGLE_ADS_CLIENT_ID"),
          clientSecret: required("GOOGLE_ADS_CLIENT_SECRET"),
          refreshToken: required("GOOGLE_ADS_REFRESH_TOKEN"),
        }),
    ...(process.env.GOOGLE_ADS_LOGIN_CUSTOMER_ID
      ? { loginCustomerId: process.env.GOOGLE_ADS_LOGIN_CUSTOMER_ID }
      : {}),
  };
  const result = await gateway.listCampaignInsights({
    accessToken: JSON.stringify(credentialEnvelope),
    externalAccountId: required("GOOGLE_ADS_CUSTOMER_ID"),
  });
  results.push({
    provider: "google-ads",
    mode: "read-only",
    received: result.metrics.length,
  });
}

console.log(JSON.stringify({ ok: true, results }));

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function parseJsonObject(name, value) {
  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${name} must contain valid JSON`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${name} must contain a JSON object`);
  }
  return parsed;
}
