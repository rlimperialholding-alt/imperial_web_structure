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
    await this.service.open({
      category: "INTEGRATION_CONTROL_ROOM",
      severity: input.severity,
      title: input.title,
      description: input.description,
      recommendedAction: "Ellenőrizd az Integration Control Roomot; szükség esetén indíts retry-t vagy OAuth újrahitelesítést.",
      source: `integration-control-room:${input.sourceIncidentId}:${input.connectorId ?? "platform"}`,
    });
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
