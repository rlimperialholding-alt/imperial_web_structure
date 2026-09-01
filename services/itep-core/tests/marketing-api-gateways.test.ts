import { describe, expect, it } from "vitest";
import {
  GoogleAdsApiGateway,
  MetaAdsApiGateway,
} from "../src/connectors/marketing-api-gateways.js";

const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

describe("marketing API gateways", () => {
  it("reads Meta campaign insights with a bearer token", async () => {
    let requestUrl = "";
    let authorization = "";
    const gateway = new MetaAdsApiGateway(
      "https://graph.test",
      "v25.0",
      async (input, init) => {
        requestUrl = input;
        authorization = String(
          (init?.headers as Record<string, string>).Authorization,
        );
        return json({
          data: [{
            account_id: "1",
            account_currency: "HUF",
            campaign_id: "2",
            campaign_name: "Lead",
            date_start: "2026-07-26",
            date_stop: "2026-07-26",
            impressions: "100",
            clicks: "8",
            spend: "1200",
            actions: [{ action_type: "lead", value: "2" }],
          }],
        });
      },
    );
    const result = await gateway.listCampaignInsights({
      accessToken: "secret",
      externalAccountId: "1",
    });
    expect(requestUrl).toContain("/v25.0/act_1/insights");
    expect(authorization).toBe("Bearer secret");
    expect(result.metrics[0]).toMatchObject({
      campaignName: "Lead",
      conversions: 2,
      provider: "META_ADS",
    });
  });

  it("refreshes OAuth and reads Google Ads without a mutate request", async () => {
    const methods: string[] = [];
    const urls: string[] = [];
    const gateway = new GoogleAdsApiGateway(
      "https://googleads.test",
      "v25",
      "https://oauth.test/token",
      async (input, init) => {
        urls.push(input);
        methods.push(init?.method ?? "GET");
        if (input.includes("oauth.test")) {
          return json({ access_token: "oauth-access" });
        }
        expect((init?.headers as Record<string, string>)["developer-token"])
          .toBe("developer");
        expect((init?.headers as Record<string, string>).Authorization)
          .toBe("Bearer oauth-access");
        return json([{
          results: [{
            campaign: { id: "2", name: "Search", status: "ENABLED" },
            segments: { date: "2026-07-26" },
            customer: { currencyCode: "HUF" },
            metrics: {
              impressions: "200",
              clicks: "10",
              costMicros: "2500000",
              conversions: 3,
            },
          }],
        }]);
      },
    );
    const result = await gateway.listCampaignInsights({
      accessToken: JSON.stringify({
        developerToken: "developer",
        clientId: "client",
        clientSecret: "client-secret",
        refreshToken: "refresh",
      }),
      externalAccountId: "123-456-7890",
    });
    expect(methods).toEqual(["POST", "POST"]);
    expect(urls[1]).toContain("/v25/customers/1234567890/googleAds:searchStream");
    expect(urls.every((url) => !url.toLowerCase().includes("mutate"))).toBe(true);
    expect(result.metrics[0]).toMatchObject({
      campaignName: "Search",
      spend: 2.5,
      provider: "GOOGLE_ADS",
    });
  });
});
