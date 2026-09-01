import type {
  GoogleAdsGateway,
  MetaAdsGateway,
} from "./marketing-sync-adapters.js";
import type { MarketingMetricEvent } from "./business-event-normalizers.js";

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
      ?? await this.refreshAccessToken(credentials);
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

  private async refreshAccessToken(credentials: GoogleAdsCredentialEnvelope) {
    if (!credentials.clientId || !credentials.clientSecret || !credentials.refreshToken) {
      throw new Error(
        "Google Ads credentials require accessToken or clientId, clientSecret and refreshToken",
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
  };
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
function digits(value: string, label: string) {
  const normalized = value.replace(/\D/g, "");
  if (!normalized) throw new Error(`${label} is invalid`);
  return normalized;
}
