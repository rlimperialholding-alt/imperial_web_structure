export type ConnectorOperationalStatus =
  | "HEALTHY"
  | "DEGRADED"
  | "FAILED"
  | "DISCONNECTED"
  | "REAUTH_REQUIRED"
  | "RATE_LIMITED";

export type IncidentSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface ConnectorOperationalSnapshot {
  connectorId: string;
  organizationId: string;
  kind: string;
  status: ConnectorOperationalStatus;
  lastSuccessfulSyncAt?: Date;
  lastAttemptAt?: Date;
  consecutiveFailures: number;
  pendingRetries: number;
  deadLetterCount: number;
  reauthRequired: boolean;
  rateLimitedUntil?: Date;
  lastErrorCode?: string;
  lastErrorMessage?: string;
  updatedAt: Date;
}

export interface IntegrationIncident {
  id: string;
  organizationId: string;
  connectorId?: string;
  severity: IncidentSeverity;
  type:
    | "CONNECTOR_DEGRADED"
    | "CONNECTOR_FAILED"
    | "REAUTH_REQUIRED"
    | "DEAD_LETTER_THRESHOLD"
    | "RATE_LIMIT"
    | "SYNC_STALLED";
  status: "OPEN" | "ACKNOWLEDGED" | "RESOLVED";
  title: string;
  description: string;
  firstObservedAt: Date;
  lastObservedAt: Date;
  occurrenceCount: number;
  assignedTo?: string;
  resolutionNote?: string;
  resolvedAt?: Date;
}

export interface RetryCommand {
  id: string;
  organizationId: string;
  connectorId: string;
  operation: string;
  payload: unknown;
  attempt: number;
  maxAttempts: number;
  nextAttemptAt: Date;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "DEAD_LETTER";
  lastError?: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface DeadLetterItem {
  id: string;
  organizationId: string;
  connectorId: string;
  operation: string;
  payload: unknown;
  totalAttempts: number;
  lastError: string;
  failedAt: Date;
  acknowledgedAt?: Date;
  acknowledgedBy?: string;
  resolution?: string;
}
