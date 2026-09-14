import type {
  ConnectorAccount,
  ConnectorSyncResult,
  SyncCheckpoint,
} from "./types.js";

export interface ConnectorAccountRepository {
  getById(id: string): Promise<ConnectorAccount | null>;
  save(account: ConnectorAccount): Promise<void>;
  listActive(kind?: string): Promise<ConnectorAccount[]>;
}

export interface SyncCheckpointRepository {
  get(connectorAccountId: string): Promise<SyncCheckpoint | null>;
  save(checkpoint: SyncCheckpoint): Promise<void>;
}

export interface ConnectorSecretProvider {
  getAccessToken(connectorAccountId: string): Promise<string>;
  invalidate(connectorAccountId: string): Promise<void>;
}

export interface ConnectorSyncAdapter {
  sync(input: {
    account: ConnectorAccount;
    checkpoint: SyncCheckpoint | null;
    accessToken: string;
  }): Promise<ConnectorSyncResult>;
}
