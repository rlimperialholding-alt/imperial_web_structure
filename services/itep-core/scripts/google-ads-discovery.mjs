import { GoogleAdsApiGateway } from "../dist/src/connectors/index.js";

if (process.env.READ_ONLY_MODE !== "true") {
  throw new Error("READ_ONLY_MODE=true is required; write operations are forbidden.");
}

const serviceAccount = parseJsonObject(
  "GOOGLE_ADS_SERVICE_ACCOUNT_JSON",
  required("GOOGLE_ADS_SERVICE_ACCOUNT_JSON"),
);
const gateway = new GoogleAdsApiGateway(
  process.env.GOOGLE_ADS_API_BASE_URL ?? "https://googleads.googleapis.com",
  process.env.GOOGLE_ADS_API_VERSION ?? "v25",
  process.env.GOOGLE_OAUTH_TOKEN_URL ?? "https://oauth2.googleapis.com/token",
);
const accounts = await gateway.discoverAccessibleAccounts({
  accessToken: JSON.stringify({
    developerToken: required("GOOGLE_ADS_DEVELOPER_TOKEN"),
    serviceAccount,
  }),
});

console.log(JSON.stringify({
  ok: true,
  mode: "read-only",
  count: accounts.length,
  accounts,
}, null, 2));

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
