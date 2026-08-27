import { describe, expect, it } from "vitest";
import { EnvironmentConnectorSecretProvider } from "../src/connectors/environment-secret-provider.js";
describe("EnvironmentConnectorSecretProvider", () => {
  it("reads connector token map", async () => {
    const provider=new EnvironmentConnectorSecretProvider(JSON.stringify({"gmail-1":{accessToken:"secret"}}));
    await expect(provider.getAccessToken("gmail-1")).resolves.toBe("secret");
  });
  it("rejects missing token", async () => {
    await expect(new EnvironmentConnectorSecretProvider("{}").getAccessToken("x")).rejects.toThrow("missing");
  });
  it("reads a normalized per-connector environment secret", async () => {
    const provider = new EnvironmentConnectorSecretProvider("{}", {
      CONNECTOR_ACCESS_TOKEN_META_ADS_LIVE: "meta-secret",
    });
    await expect(provider.getAccessToken("meta-ads-live"))
      .resolves.toBe("meta-secret");
  });
  it("serializes a provider credential envelope from the central secret map", async () => {
    const provider = new EnvironmentConnectorSecretProvider(JSON.stringify({
      "google-ads-live": {
        developerToken: "developer-secret",
        serviceAccount: {
          client_email: "reporting@example.test",
          private_key: "private-secret",
        },
      },
    }));
    const value = await provider.getAccessToken("google-ads-live");
    expect(JSON.parse(value)).toMatchObject({
      developerToken: "developer-secret",
      serviceAccount: { client_email: "reporting@example.test" },
    });
  });
});
