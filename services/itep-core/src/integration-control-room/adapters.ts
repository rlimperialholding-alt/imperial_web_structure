import type { ConnectorSyncOrchestrator } from "../connectors/sync-orchestrator.js";
import type { HumanAnneIncidentService } from "../human-anne/incident-service.js";
import type { ConnectorOperationExecutor, HumanAnneIncidentPublisher } from "./ports.js";

export class OrchestratorOperationExecutor implements ConnectorOperationExecutor {
  constructor(private readonly orchestrator: ConnectorSyncOrchestrator) {}
  async execute(input: { connectorId: string; operation: string; payload: unknown }) {
    if (input.operation !== "SYNC") throw new Error(`Unsupported connector operation: ${input.operation}`);
    await this.orchestrator.syncAccount(input.connectorId);
  }
}

export class HumanAnnePublisherAdapter implements HumanAnneIncidentPublisher {
  constructor(private readonly service: HumanAnneIncidentService) {}
  async publish(input: {
    organizationId: string; connectorId?: string;
    severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
    title: string; description: string; sourceIncidentId: string;
  }) {
    // The Integration Control Room has already persisted this incident without
    // a human assignee. Do not mirror technical faults into Human Anne's queue.
    void this.service;
    void input;
  }
}

export class UnassignedTechnicalIncidentWriter {
  async open(_input: {
    category: string; severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
    title: string; description: string; recommendedAction: string;
    source: string; createdAt: Date;
  }) {
    // The orchestrator observer writes the canonical unassigned Control Room
    // incident. This compatibility sink deliberately creates no human task.
    return { routedTo: "integration-control-room", assignedTo: null };
  }
}


export class ControlRoomSyncObserver {
  constructor(private readonly service: import("./service.js").IntegrationControlRoomService) {}
  success(input: { organizationId: string; connectorId: string; kind: string }) {
    return this.service.recordConnectorSuccess(input);
  }
  failure(input: { organizationId: string; connectorId: string; kind: string; errorMessage: string; reauthRequired: boolean }) {
    return this.service.recordConnectorFailure(input);
  }
}
