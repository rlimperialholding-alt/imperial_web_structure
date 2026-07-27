import type { Clock, IdGenerator } from "../application/ports.js";
import type {
  ConnectorAccountRepository,
  ConnectorSecretProvider,
  ConnectorSyncAdapter,
  SyncCheckpointRepository,
} from "./ports.js";
import type { ConnectorAccount } from "./types.js";
import { assertConnectorOwnership } from "./account-policy.js";

export interface ConnectorIncidentWriter {
  open(input: {
    category: string;
    severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
    title: string;
    description: string;
    recommendedAction: string;
    source: string;
    createdAt: Date;
  }): Promise<unknown>;
}

export interface ConnectorSyncObserver {
  success(input: { organizationId: string; connectorId: string; kind: string }): Promise<void>;
  failure(input: { organizationId: string; connectorId: string; kind: string; errorMessage: string; reauthRequired: boolean }): Promise<void>;
}

export class ConnectorSyncOrchestrator {
  constructor(
    private readonly accounts: ConnectorAccountRepository,
    private readonly checkpoints: SyncCheckpointRepository,
    private readonly secrets: ConnectorSecretProvider,
    private readonly adapters: Record<string, ConnectorSyncAdapter>,
    private readonly incidents: ConnectorIncidentWriter,
    private readonly clock: Clock,
    private readonly ids: IdGenerator,
    private readonly observer?: ConnectorSyncObserver,
  ) {}

  async syncAccount(accountId: string) {
    const account = await this.accounts.getById(accountId);
    if (!account) throw new Error(`Connector account not found: ${accountId}`);
    assertConnectorOwnership(account);

    const adapter = this.adapters[account.kind];
    if (!adapter) throw new Error(`No adapter registered for ${account.kind}`);

    const now = this.clock.now();
    try {
      const token = await this.secrets.getAccessToken(account.id);
      const checkpoint = await this.checkpoints.get(account.id);
      const result = await adapter.sync({
        account,
        checkpoint,
        accessToken: token,
      });

      const cursor = result.nextCheckpoint.cursor ?? checkpoint?.cursor;
      const historyId = result.nextCheckpoint.historyId ?? checkpoint?.historyId;
      const syncToken = result.nextCheckpoint.syncToken ?? checkpoint?.syncToken;
      const expiresAt = result.nextCheckpoint.expiresAt ?? checkpoint?.expiresAt;
      await this.checkpoints.save({
        id: checkpoint?.id ?? this.ids.next(),
        connectorAccountId: account.id,
        ...(cursor ? { cursor } : {}),
        ...(historyId ? { historyId } : {}),
        ...(syncToken ? { syncToken } : {}),
        ...(expiresAt ? { expiresAt } : {}),
        updatedAt: now,
      });

      const { lastError: _previousError, ...accountWithoutError } = account;
      await this.accounts.save({
        ...accountWithoutError,
        status: result.failed > 0 ? "DEGRADED" : "ACTIVE",
        updatedAt: now,
        lastSuccessfulSyncAt: now,
        ...(result.failed > 0
          ? { lastError: `${result.failed} source events failed` }
          : {}),
      });
      await this.observer?.success({ organizationId: account.organizationId, connectorId: account.id, kind: account.kind });

      return result;
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown connector error";
      const reauth = /401|invalid_grant|unauthorized|token/i.test(message);

      await this.accounts.save({
        ...account,
        status: reauth ? "REAUTH_REQUIRED" : "ERROR",
        updatedAt: now,
        lastError: message,
      });

      await this.incidents.open({
        category: "CONNECTOR_FAILURE",
        severity: account.kind === "GMAIL" ? "CRITICAL" : "HIGH",
        title: `${account.kind} kapcsolat hibája`,
        description: message,
        recommendedAction: reauth
          ? "A Human Anne indítsa újra az OAuth-hitelesítést."
          : "A Human Anne ellenőrizze a connector naplóját és a szolgáltatás állapotát.",
        source: `connector:${account.id}`,
        createdAt: now,
      });

      await this.observer?.failure({
        organizationId: account.organizationId, connectorId: account.id,
        kind: account.kind, errorMessage: message, reauthRequired: reauth,
      });
      if (reauth) await this.secrets.invalidate(account.id);
      throw error;
    }
  }

  async syncAll(kind?: string) {
    const accounts = await this.accounts.listActive(kind);
    const results: Array<{
      accountId: string;
      ok: boolean;
      received?: number;
      error?: string;
    }> = [];

    for (const account of accounts) {
      try {
        const result = await this.syncAccount(account.id);
        results.push({
          accountId: account.id,
          ok: true,
          received: result.received,
        });
      } catch (error) {
        results.push({
          accountId: account.id,
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    return results;
  }
}
