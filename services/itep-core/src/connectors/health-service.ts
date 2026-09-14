import type { ConnectorAccountRepository } from "./ports.js";

export interface ConnectorHealthItem {
  accountId: string;
  kind: string;
  status: string;
  healthy: boolean;
  reason: string;
  lastSuccessfulSyncAt?: Date;
}

export class ConnectorHealthService {
  constructor(
    private readonly accounts: ConnectorAccountRepository,
    private readonly now: () => Date,
    private readonly staleAfterMs = 30 * 60 * 1000,
  ) {}

  async inspect(kind?: string): Promise<ConnectorHealthItem[]> {
    const accounts = await this.accounts.listActive(kind);
    const now = this.now();

    return accounts.map((account) => {
      if (account.status === "ERROR" || account.status === "REAUTH_REQUIRED") {
        return {
          accountId: account.id,
          kind: account.kind,
          status: account.status,
          healthy: false,
          reason: account.lastError ?? "Connector is not operational",
          ...(account.lastSuccessfulSyncAt
            ? { lastSuccessfulSyncAt: account.lastSuccessfulSyncAt }
            : {}),
        };
      }

      if (!account.lastSuccessfulSyncAt) {
        return {
          accountId: account.id,
          kind: account.kind,
          status: account.status,
          healthy: false,
          reason: "Connector has never completed a successful sync",
        };
      }

      const age = now.getTime() - account.lastSuccessfulSyncAt.getTime();
      return {
        accountId: account.id,
        kind: account.kind,
        status: account.status,
        healthy: age <= this.staleAfterMs && account.status === "ACTIVE",
        reason:
          age > this.staleAfterMs
            ? "Last successful sync is stale"
            : account.status === "DEGRADED"
              ? "Connector completed with partial failures"
              : "Healthy",
        lastSuccessfulSyncAt: account.lastSuccessfulSyncAt,
      };
    });
  }
}
