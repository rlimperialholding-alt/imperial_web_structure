import type { ConnectorSecretProvider } from "./ports.js";

interface TokenEntry {
  accessToken?: string;
  credentialEnvelope?: Record<string, unknown>;
  developerToken?: string;
}

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
    const token = resolveEntry(entry) ?? this.env[envName];
    if (!token) throw new Error(`Access token missing for connector ${connectorAccountId}`);
    return token;
  }
  async invalidate(_connectorAccountId: string): Promise<void> {
    // Environment secrets are immutable at runtime. Production must use a vault implementation.
  }
}

function resolveEntry(entry: string | TokenEntry | undefined) {
  if (typeof entry === "string") return entry;
  if (!entry) return undefined;
  if (entry.credentialEnvelope) {
    return JSON.stringify(entry.credentialEnvelope);
  }
  if (entry.developerToken) {
    return JSON.stringify(entry);
  }
  return entry.accessToken;
}
