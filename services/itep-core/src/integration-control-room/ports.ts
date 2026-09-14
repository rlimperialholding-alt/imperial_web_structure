import type {
  ConnectorOperationalSnapshot,
  DeadLetterItem,
  IntegrationIncident,
  RetryCommand,
} from "./domain.js";

export interface IntegrationControlRoomRepository {
  listConnectorSnapshots(organizationId: string): Promise<ConnectorOperationalSnapshot[]>;
  getConnectorSnapshot(
    organizationId: string,
    connectorId: string,
  ): Promise<ConnectorOperationalSnapshot | null>;
  saveConnectorSnapshot(snapshot: ConnectorOperationalSnapshot): Promise<void>;

  listOpenIncidents(organizationId: string): Promise<IntegrationIncident[]>;
  getIncident(id: string): Promise<IntegrationIncident | null>;
  saveIncident(incident: IntegrationIncident): Promise<void>;

  listDueRetries(now: Date, limit: number): Promise<RetryCommand[]>;
  getRetry(id: string): Promise<RetryCommand | null>;
  saveRetry(command: RetryCommand): Promise<void>;

  listDeadLetters(organizationId: string): Promise<DeadLetterItem[]>;
  getDeadLetter(id: string): Promise<DeadLetterItem | null>;
  saveDeadLetter(item: DeadLetterItem): Promise<void>;
}

export interface ConnectorOperationExecutor {
  execute(input: {
    connectorId: string;
    operation: string;
    payload: unknown;
  }): Promise<void>;
}

export interface HumanAnneIncidentPublisher {
  publish(input: {
    organizationId: string;
    connectorId?: string;
    severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
    title: string;
    description: string;
    sourceIncidentId: string;
  }): Promise<void>;
}
