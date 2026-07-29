import type {
  GoogleAdsGateway,
  MetaAdsGateway,
} from "./marketing-sync-adapters.js";
import type { MarketingMetricEvent } from "./business-event-normalizers.js";
import { createSign } from "node:crypto";

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class MetaAdsApiGateway implements MetaAdsGateway {
  constructor(
    private readonly baseUrl: string,
    private readonly apiVersion: string,
    private readonly fetcher: FetchLike = fetch,
  ) {}

  async listCampaignInsights(input: {
    accessToken: string;
    externalAccountId: string;
    cursor?: string;
  }) {
    const accountId = input.externalAccountId.startsWith("act_")
      ? input.externalAccountId
      : `act_${input.externalAccountId}`;
    const url = new URL(
      `/${this.apiVersion}/${encodeURIComponent(accountId)}/insights`,
      this.baseUrl,
    );
    url.searchParams.set(
      "fields",
      [
        "account_id",
        "account_currency",
        "campaign_id",
        "campaign_name",
        "date_start",
        "date_stop",
        "impressions",
        "clicks",
        "spend",
        "actions",
      ].join(","),
    );
    url.searchParams.set("level", "campaign");
    url.searchParams.set("date_preset", "last_30d");
    url.searchParams.set("time_increment", "1");
    url.searchParams.set("limit", "100");
    if (input.cursor) url.searchParams.set("after", input.cursor);

    const response = await this.fetcher(url.toString(), {
      method: "GET",
      headers: {
        Authorization: `Bearer ${input.accessToken}`,
        Accept: "application/json",
      },
    });
    await assertSuccess(response, "Meta Ads");
    const payload = (await response.json()) as any;
    const metrics: MarketingMetricEvent[] = (payload.data ?? []).map(
      (item: any) => ({
        organizationId: "",
        provider: "META_ADS",
        accountId: String(item.account_id ?? accountId.replace(/^act_/, "")),
        campaignId: String(item.campaign_id),
        campaignName: String(item.campaign_name ?? item.campaign_id),
        dateStart: String(item.date_start),
        dateStop: String(item.date_stop ?? item.date_start),
        impressions: number(item.impressions),
        clicks: number(item.clicks),
        spend: number(item.spend),
        currency: optionalString(item.account_currency),
        conversions: conversionCount(item.actions),
        updatedAt: endOfUtcDay(item.date_stop ?? item.date_start),
      }),
    );
    return {
      metrics,
      ...(payload.paging?.cursors?.after && payload.paging?.next
        ? { nextCursor: String(payload.paging.cursors.after) }
        : {}),
    };
  }
}

interface GoogleAdsCredentialEnvelope {
  developerToken: string;
  accessToken?: string;
  clientId?: string;
  clientSecret?: string;
  refreshToken?: string;
  loginCustomerId?: string;
  serviceAccount?: {
    clientEmail: string;
    privateKey: string;
  };
}

export class GoogleAdsApiGateway implements GoogleAdsGateway {
  constructor(
    private readonly baseUrl: string,
    private readonly apiVersion: string,
    private readonly tokenUrl: string,
    private readonly fetcher: FetchLike = fetch,
  ) {}

  async listCampaignInsights(input: {
    accessToken: string;
    externalAccountId: string;
  }) {
    const credentials = parseGoogleCredentials(input.accessToken);
    const oauthAccessToken = credentials.accessToken
      ?? await this.obtainAccessToken(credentials);
    const customerId = digits(input.externalAccountId, "Google Ads customer ID");
    const url = new URL(
      `/${this.apiVersion}/customers/${customerId}/googleAds:searchStream`,
      this.baseUrl,
    );
    const headers: Record<string, string> = {
      Authorization: `Bearer ${oauthAccessToken}`,
      "developer-token": credentials.developerToken,
      Accept: "application/json",
      "Content-Type": "application/json",
    };
    if (credentials.loginCustomerId) {
      headers["login-customer-id"] = digits(
        credentials.loginCustomerId,
        "Google Ads login customer ID",
      );
    }
    const response = await this.fetcher(url.toString(), {
      method: "POST",
      headers,
      body: JSON.stringify({
        query: [
          "SELECT campaign.id, campaign.name, campaign.status,",
          "segments.date, customer.currency_code, metrics.impressions,",
          "metrics.clicks, metrics.cost_micros, metrics.conversions",
          "FROM campaign",
          "WHERE segments.date DURING LAST_30_DAYS",
          "ORDER BY segments.date DESC",
        ].join(" "),
      }),
    });
    await assertSuccess(response, "Google Ads");
    const payload = (await response.json()) as any;
    const batches = Array.isArray(payload) ? payload : [payload];
    const metrics: MarketingMetricEvent[] = batches.flatMap((batch: any) =>
      (batch.results ?? []).map((item: any) => ({
        organizationId: "",
        provider: "GOOGLE_ADS",
        accountId: customerId,
        campaignId: String(item.campaign?.id),
        campaignName: String(item.campaign?.name ?? item.campaign?.id),
        campaignStatus: optionalString(item.campaign?.status),
        dateStart: String(item.segments?.date),
        dateStop: String(item.segments?.date),
        impressions: number(item.metrics?.impressions),
        clicks: number(item.metrics?.clicks),
        spend: number(item.metrics?.costMicros) / 1_000_000,
        currency: optionalString(item.customer?.currencyCode),
        conversions: number(item.metrics?.conversions),
        updatedAt: endOfUtcDay(item.segments?.date),
      })),
    );
    return { metrics };
  }

  async discoverAccessibleAccounts(input: { accessToken: string }) {
    const credentials = parseGoogleCredentials(input.accessToken);
    const oauthAccessToken = credentials.accessToken
      ?? await this.obtainAccessToken(credentials);
    const headers = this.googleAdsHeaders(credentials, oauthAccessToken);
    const listUrl = new URL(
      `/${this.apiVersion}/customers:listAccessibleCustomers`,
      this.baseUrl,
    );
    const listResponse = await this.fetcher(listUrl.toString(), {
      method: "GET",
      headers,
    });
    await assertSuccess(listResponse, "Google Ads");
    const listPayload = (await listResponse.json()) as any;
    const customerIds = (listPayload.resourceNames ?? [])
      .map((name: unknown) => String(name).match(/customers\/(\d+)/)?.[1])
      .filter((id: string | undefined): id is string => Boolean(id));
    const discovered = [];

    for (const customerId of customerIds) {
      const account = await this.readCustomerSummary(
        customerId,
        headers,
        credentials.loginCustomerId,
      );
      discovered.push(account);
      if (account.manager) {
        discovered.push(...await this.readDirectCustomerClients(
          customerId,
          headers,
        ));
      }
    }

    return [...new Map(
      discovered.map((account) => [account.customerId, account]),
    ).values()];
  }

  private async readCustomerSummary(
    customerId: string,
    baseHeaders: Record<string, string>,
    loginCustomerId?: string,
  ) {
    const headers = {
      ...baseHeaders,
      ...(loginCustomerId
        ? { "login-customer-id": digits(loginCustomerId, "Google Ads login customer ID") }
        : {}),
    };
    const response = await this.googleAdsSearch(customerId, headers, [
      "SELECT customer.id, customer.descriptive_name, customer.manager,",
      "customer.currency_code, customer.time_zone",
      "FROM customer LIMIT 1",
    ].join(" "));
    const payload = (await response.json()) as any;
    const row = flattenGoogleAdsResults(payload)[0] ?? {};
    return {
      customerId,
      descriptiveName: optionalString(row.customer?.descriptiveName),
      manager: Boolean(row.customer?.manager),
      currencyCode: optionalString(row.customer?.currencyCode),
      timeZone: optionalString(row.customer?.timeZone),
      level: 0,
    };
  }

  private async readDirectCustomerClients(
    managerCustomerId: string,
    baseHeaders: Record<string, string>,
  ) {
    const headers = {
      ...baseHeaders,
      "login-customer-id": managerCustomerId,
    };
    const response = await this.googleAdsSearch(managerCustomerId, headers, [
      "SELECT customer_client.client_customer,",
      "customer_client.descriptive_name, customer_client.manager,",
      "customer_client.level, customer_client.status",
      "FROM customer_client WHERE customer_client.level <= 1",
    ].join(" "));
    const payload = (await response.json()) as any;
    return flattenGoogleAdsResults(payload)
      .map((row: any) => row.customerClient)
      .filter(Boolean)
      .map((customerClient: any) => ({
        customerId: String(customerClient.clientCustomer ?? "")
          .replace(/\D/g, ""),
        descriptiveName: optionalString(customerClient.descriptiveName),
        manager: Boolean(customerClient.manager),
        status: optionalString(customerClient.status),
        level: number(customerClient.level),
        loginCustomerId: managerCustomerId,
      }))
      .filter((account: { customerId: string }) => account.customerId);
  }

  private async googleAdsSearch(
    customerId: string,
    headers: Record<string, string>,
    query: string,
  ) {
    const url = new URL(
      `/${this.apiVersion}/customers/${digits(customerId, "Google Ads customer ID")}/googleAds:searchStream`,
      this.baseUrl,
    );
    const response = await this.fetcher(url.toString(), {
      method: "POST",
      headers,
      body: JSON.stringify({ query }),
    });
    await assertSuccess(response, "Google Ads");
    return response;
  }

  private googleAdsHeaders(
    credentials: GoogleAdsCredentialEnvelope,
    oauthAccessToken: string,
  ) {
    return {
      Authorization: `Bearer ${oauthAccessToken}`,
      "developer-token": credentials.developerToken,
      Accept: "application/json",
      "Content-Type": "application/json",
    };
  }

  private async obtainAccessToken(credentials: GoogleAdsCredentialEnvelope) {
    if (credentials.serviceAccount) {
      return this.createServiceAccountAccessToken(credentials.serviceAccount);
    }
    return this.refreshAccessToken(credentials);
  }

  private async createServiceAccountAccessToken(serviceAccount: {
    clientEmail: string;
    privateKey: string;
  }) {
    const issuedAt = Math.floor(Date.now() / 1000);
    const encodedHeader = base64UrlJson({ alg: "RS256", typ: "JWT" });
    const encodedPayload = base64UrlJson({
      iss: serviceAccount.clientEmail,
      scope: "https://www.googleapis.com/auth/adwords",
      aud: this.tokenUrl,
      iat: issuedAt,
      exp: issuedAt + 3600,
    });
    const unsignedAssertion = `${encodedHeader}.${encodedPayload}`;
    const signer = createSign("RSA-SHA256");
    signer.update(unsignedAssertion);
    signer.end();
    const signature = signer
      .sign(serviceAccount.privateKey)
      .toString("base64url");
    const body = new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${unsignedAssertion}.${signature}`,
    });
    const response = await this.fetcher(this.tokenUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    });
    await assertSuccess(response, "Google OAuth");
    const payload = (await response.json()) as any;
    if (!payload.access_token) throw new Error("Google OAuth response has no access token");
    return String(payload.access_token);
  }

  private async refreshAccessToken(credentials: GoogleAdsCredentialEnvelope) {
    if (!credentials.clientId || !credentials.clientSecret || !credentials.refreshToken) {
      throw new Error(
        "Google Ads credentials require accessToken, serviceAccount, or clientId, clientSecret and refreshToken",
      );
    }
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      client_id: credentials.clientId,
      client_secret: credentials.clientSecret,
      refresh_token: credentials.refreshToken,
    });
    const response = await this.fetcher(this.tokenUrl, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: body.toString(),
    });
    await assertSuccess(response, "Google OAuth");
    const payload = (await response.json()) as any;
    if (!payload.access_token) throw new Error("Google OAuth response has no access token");
    return String(payload.access_token);
  }
}

function parseGoogleCredentials(raw: string): GoogleAdsCredentialEnvelope {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("Google Ads connector secret must be a JSON credential envelope");
  }
  if (!parsed || typeof parsed !== "object") {
    throw new Error("Google Ads connector secret must be a JSON object");
  }
  const input = parsed as Record<string, unknown>;
  const developerToken = optionalString(input.developerToken);
  if (!developerToken) throw new Error("Google Ads developerToken is required");
  const serviceAccount = parseGoogleServiceAccount(input.serviceAccount);
  return {
    developerToken,
    ...(optionalString(input.accessToken)
      ? { accessToken: optionalString(input.accessToken) }
      : {}),
    ...(optionalString(input.clientId) ? { clientId: optionalString(input.clientId) } : {}),
    ...(optionalString(input.clientSecret)
      ? { clientSecret: optionalString(input.clientSecret) }
      : {}),
    ...(optionalString(input.refreshToken)
      ? { refreshToken: optionalString(input.refreshToken) }
      : {}),
    ...(optionalString(input.loginCustomerId)
      ? { loginCustomerId: optionalString(input.loginCustomerId) }
      : {}),
    ...(serviceAccount ? { serviceAccount } : {}),
  };
}

function parseGoogleServiceAccount(value: unknown) {
  if (value === undefined || value === null || value === "") return undefined;
  if (!value || typeof value !== "object") {
    throw new Error("Google Ads serviceAccount must be a JSON object");
  }
  const input = value as Record<string, unknown>;
  const clientEmail =
    optionalString(input.clientEmail) ?? optionalString(input.client_email);
  const privateKey =
    optionalString(input.privateKey) ?? optionalString(input.private_key);
  if (!clientEmail || !privateKey) {
    throw new Error(
      "Google Ads serviceAccount requires client_email and private_key",
    );
  }
  return { clientEmail, privateKey };
}

function base64UrlJson(value: unknown) {
  return Buffer.from(JSON.stringify(value), "utf8").toString("base64url");
}

async function assertSuccess(response: Response, provider: string) {
  if (response.ok) return;
  const body = (await response.text()).slice(0, 500);
  throw new Error(`${provider} API ${response.status}: ${body}`);
}
function optionalString(value: unknown) {
  return value === undefined || value === null || value === ""
    ? undefined
    : String(value);
}
function number(value: unknown) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}
function conversionCount(actions: unknown) {
  if (!Array.isArray(actions)) return 0;
  return actions
    .filter((action) =>
      /lead|purchase|complete_registration|contact/i.test(
        String(action?.action_type ?? ""),
      ),
    )
    .reduce((sum, action) => sum + number(action?.value), 0);
}
function endOfUtcDay(value: unknown) {
  const parsed = new Date(`${String(value)}T23:59:59.999Z`);
  return Number.isNaN(parsed.getTime()) ? new Date(0) : parsed;
}
function flattenGoogleAdsResults(payload: any) {
  const batches = Array.isArray(payload) ? payload : [payload];
  return batches.flatMap((batch: any) => batch.results ?? []);
}
function digits(value: string, label: string) {
  const normalized = value.replace(/\D/g, "");
  if (!normalized) throw new Error(`${label} is invalid`);
  return normalized;
}
