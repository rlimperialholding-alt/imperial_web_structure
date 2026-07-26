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
});
