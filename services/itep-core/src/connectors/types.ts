export type ConnectorKind =
  | "GMAIL"
  | "CALENDAR"
  | "DRIVE"
  | "BILLINGO"
  | "BANK"
  | "CRM"
  | "GOVERNMENT_PORTAL"
  | "META_ADS"
  | "GOOGLE_ADS"
  | "WHATSAPP_BUSINESS";
export type ConnectorScope = "GROUP" | "LEGAL_ENTITY";
export type ConnectorStatus =
  | "DISCONNECTED"
  | "CONNECTING"
  | "ACTIVE"
  | "DEGRADED"
  | "ERROR"
  | "REAUTH_REQUIRED";

export interface ConnectorAccount {
  id: string;
  organizationId: string;
  kind: ConnectorKind;
  scope: ConnectorScope;
  scopeKey: string;
  legalEntityId?: string;
  externalAccountId: string;
  displayName: string;
  status: ConnectorStatus;
  scopes: string[];
  configuration?: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
  lastSuccessfulSyncAt?: Date;
  lastError?: string;
}

export interface LegalEntity {
  id: string;
  organizationId: string;
  slug: string;
  legalName: string;
  taxNumber?: string;
  status: "ACTIVE" | "INACTIVE";
  metadata?: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
}

export interface SyncCheckpoint {
  id: string;
  connectorAccountId: string;
  cursor?: string;
  historyId?: string;
  syncToken?: string;
  expiresAt?: Date;
  updatedAt: Date;
}

export interface ConnectorSyncResult {
  received: number;
  ingested: number;
  ignored: number;
  failed: number;
  nextCheckpoint: {
    cursor?: string | undefined;
    historyId?: string | undefined;
    syncToken?: string | undefined;
    expiresAt?: Date | undefined;
  };
}
