const token = process.env.META_ADS_ACCESS_TOKEN;
const adAccountId = process.env.META_ADS_AD_ACCOUNT_ID;
const base = "https://graph.facebook.com/v25.0";
const andreaEmail = "molnar.andrea@imperialholding.hu";

if (!token) throw new Error("META_ADS_ACCESS_TOKEN is missing");

const failures = [];
async function graph(path, params = {}, accessToken = token, label = path) {
  const url = new URL(`${base}/${String(path).replace(/^\/+/, "")}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  url.searchParams.set("access_token", accessToken);
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok || payload.error) {
      failures.push({
        probe: label,
        http: response.status,
        code: payload?.error?.code ?? null,
        subcode: payload?.error?.error_subcode ?? null,
      });
      return null;
    }
    return payload;
  } catch {
    failures.push({ probe: label, http: null, code: "NETWORK", subcode: null });
    return null;
  }
}

async function edgeCount(businessId, edge, params = {}) {
  const payload = await graph(
    `${businessId}/${edge}`,
    { fields: "id", limit: 100, ...params },
    token,
    edge,
  );
  return Array.isArray(payload?.data) ? payload.data.length : null;
}

const permissionsPayload = await graph("me/permissions", {}, token, "permissions");
const grantedPermissions = (permissionsPayload?.data ?? [])
  .filter((row) => row.status === "granted")
  .map((row) => row.permission)
  .sort();

const debugPayload = await graph(
  "debug_token",
  { input_token: token },
  token,
  "debug_token",
);

const accountsPayload = await graph(
  "me/accounts",
  { fields: "id,tasks,access_token", limit: 100 },
  token,
  "managed_pages",
);
const managedPages = Array.isArray(accountsPayload?.data) ? accountsPayload.data : [];

const businessesPayload = await graph(
  "me/businesses",
  { fields: "id,name", limit: 100 },
  token,
  "businesses",
);
const businesses = Array.isArray(businessesPayload?.data) ? businessesPayload.data : [];

const adAccountPayload = adAccountId
  ? await graph(adAccountId, { fields: "business{id,name}" }, token, "ad_account_business")
  : null;

const businessById = new Map();
for (const business of businesses) {
  if (business?.id) businessById.set(String(business.id), business);
}
if (adAccountPayload?.business?.id) {
  businessById.set(String(adAccountPayload.business.id), adAccountPayload.business);
}

const businessSummaries = [];
for (const business of businessById.values()) {
  const id = String(business.id);
  const pendingAndrea = await edgeCount(id, "pending_users", { email: andreaEmail });
  const usersPayload = await graph(
    `${id}/business_users`,
    { fields: "id,email,role", limit: 100 },
    token,
    "business_users",
  );
  const users = Array.isArray(usersPayload?.data) ? usersPayload.data : [];
  businessSummaries.push({
    isNextstep: /nextstep/i.test(String(business.name ?? "")),
    ownedPages: await edgeCount(id, "owned_pages"),
    clientPages: await edgeCount(id, "client_pages"),
    pendingClientPages: await edgeCount(id, "pending_client_pages"),
    pendingOwnedPages: await edgeCount(id, "pending_owned_pages"),
    andreaActive: users.some(
      (row) => String(row.email ?? "").toLowerCase() === andreaEmail,
    ),
    andreaPendingCount: pendingAndrea,
  });
}

let pagePartnerReadable = 0;
let nextstepAlreadyPartner = 0;
const nextstepBusinessIds = new Set(
  [...businessById.values()]
    .filter((row) => /nextstep/i.test(String(row.name ?? "")))
    .map((row) => String(row.id)),
);

for (const page of managedPages) {
  if (!page?.id || !page?.access_token) continue;
  const agenciesPayload = await graph(
    `${page.id}/agencies`,
    { fields: "id,name", limit: 100 },
    page.access_token,
    "page_agencies",
  );
  const agencies = Array.isArray(agenciesPayload?.data) ? agenciesPayload.data : null;
  if (!agencies) continue;
  pagePartnerReadable += 1;
  const matches = agencies.filter((row) => /nextstep/i.test(String(row.name ?? "")));
  if (matches.length) nextstepAlreadyPartner += 1;
  for (const row of matches) if (row?.id) nextstepBusinessIds.add(String(row.id));
}

const nextstepSummaries = businessSummaries.filter((row) => row.isNextstep);
const summary = {
  tokenValid: Boolean(debugPayload?.data?.is_valid ?? permissionsPayload),
  tokenType: debugPayload?.data?.type ?? null,
  grantedPermissions,
  businessManagementGranted: grantedPermissions.includes("business_management"),
  managedPageCount: managedPages.length,
  pagePartnerReadable,
  nextstepBusinessVisible: nextstepBusinessIds.size > 0,
  nextstepAlreadyPartnerPageCount: nextstepAlreadyPartner,
  businessCount: businessById.size,
  totalPendingClientPages: businessSummaries.reduce(
    (sum, row) => sum + (row.pendingClientPages ?? 0),
    0,
  ),
  nextstepPendingClientPages: nextstepSummaries.reduce(
    (sum, row) => sum + (row.pendingClientPages ?? 0),
    0,
  ),
  andreaActiveInAnyBusiness: businessSummaries.some((row) => row.andreaActive),
  andreaPendingInAnyBusiness: businessSummaries.some(
    (row) => (row.andreaPendingCount ?? 0) > 0,
  ),
  failures,
};

console.log(JSON.stringify(summary, null, 2));
