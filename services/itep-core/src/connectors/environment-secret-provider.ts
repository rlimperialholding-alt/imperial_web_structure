import type { ConnectorSecretProvider } from "./ports.js";

interface TokenEntry { accessToken: string; }

export class EnvironmentConnectorSecretProvider implements ConnectorSecretProvider {
  constructor(
    private readonly rawJson = process.env.CONNECTOR_ACCESS_TOKENS_JSON ?? "{}",
    private readonly env: NodeJS.ProcessEnv = process.env,
  ) {}
  async getAccessToken(connectorAccountId: string): Promise<string> {
    const parsed = JSON.parse(this.rawJson) as Record<string, string | TokenEntry>;
    const entry = parsed[connectorAccountId];
    const envName = `CONNECTOR_ACCESS_TOKEN_${connectorAccountId
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, "_")}`;
    const token = (typeof entry === "string" ? entry : entry?.accessToken)
      ?? this.env[envName];
    if (!token) throw new Error(`Access token missing for connector ${connectorAccountId}`);
    return token;
  }
  async invalidate(_connectorAccountId: string): Promise<void> {
    // Environment secrets are immutable at runtime. Production must use a vault implementation.
  }
}
