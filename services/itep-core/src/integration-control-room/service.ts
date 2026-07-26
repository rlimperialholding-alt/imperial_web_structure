import { randomUUID } from "node:crypto";
import type {
  ConnectorOperationalSnapshot,
  DeadLetterItem,
  IntegrationIncident,
  RetryCommand,
} from "./domain.js";
import type {
  ConnectorOperationExecutor,
  HumanAnneIncidentPublisher,
  IntegrationControlRoomRepository,
} from "./ports.js";
import {
  calculateRetryDelaySeconds,
  defaultIntegrationPolicy,
  deriveOperationalStatus,
  incidentSeverityFor,
  type IntegrationPolicy,
} from "./policy.js";

export class IntegrationControlRoomService {
  constructor(
    private readonly repository: IntegrationControlRoomRepository,
    private readonly executor: ConnectorOperationExecutor,
    private readonly incidentPublisher: HumanAnneIncidentPublisher,
    private readonly now: () => Date,
    private readonly policy: IntegrationPolicy = defaultIntegrationPolicy,
  ) {}

  async dashboard(organizationId: string) {
    const connectors =
      await this.repository.listConnectorSnapshots(organizationId);
    const incidents =
      await this.repository.listOpenIncidents(organizationId);
    const deadLetters =
      await this.repository.listDeadLetters(organizationId);

    return {
      generatedAt: this.now(),
      totals: {
        connectors: connectors.length,
        healthy: connectors.filter((item) => item.status === "HEALTHY").length,
        degraded: connectors.filter((item) =>
          ["DEGRADED", "RATE_LIMITED"].includes(item.status),
        ).length,
        failed: connectors.filter((item) =>
          ["FAILED", "REAUTH_REQUIRED", "DISCONNECTED"].includes(item.status),
        ).length,
        openIncidents: incidents.length,
        deadLetters: deadLetters.filter((item) => !item.acknowledgedAt).length,
      },
      connectors,
      incidents,
      deadLetters,
    };
  }

  async recordConnectorSuccess(input: {
    organizationId: string;
    connectorId: string;
    kind: string;
  }): Promise<ConnectorOperationalSnapshot> {
    const now = this.now();
    const current =
      await this.repository.getConnectorSnapshot(
        input.organizationId,
        input.connectorId,
      );

    const next: ConnectorOperationalSnapshot = {
      connectorId: input.connectorId,
      organizationId: input.organizationId,
      kind: input.kind,
      status: "HEALTHY",
      lastSuccessfulSyncAt: now,
      lastAttemptAt: now,
      consecutiveFailures: 0,
      pendingRetries: current?.pendingRetries ?? 0,
      deadLetterCount: current?.deadLetterCount ?? 0,
      reauthRequired: false,
      updatedAt: now,
    };
    await this.repository.saveConnectorSnapshot(next);
    return next;
  }

  async recordConnectorFailure(input: {
    organizationId: string;
    connectorId: string;
    kind: string;
    errorCode?: string;
    errorMessage: string;
    reauthRequired?: boolean;
    rateLimitedUntil?: Date;
  }): Promise<ConnectorOperationalSnapshot> {
    const now = this.now();
    const current =
      await this.repository.getConnectorSnapshot(
        input.organizationId,
        input.connectorId,
      );

    const candidate: ConnectorOperationalSnapshot = {
      connectorId: input.connectorId,
      organizationId: input.organizationId,
      kind: input.kind,
      status: current?.status ?? "DEGRADED",
      ...(current?.lastSuccessfulSyncAt
        ? { lastSuccessfulSyncAt: current.lastSuccessfulSyncAt }
        : {}),
      lastAttemptAt: now,
      consecutiveFailures: (current?.consecutiveFailures ?? 0) + 1,
      pendingRetries: current?.pendingRetries ?? 0,
      deadLetterCount: current?.deadLetterCount ?? 0,
      reauthRequired: input.reauthRequired ?? false,
      ...(input.rateLimitedUntil ? { rateLimitedUntil: input.rateLimitedUntil } : {}),
      ...(input.errorCode ? { lastErrorCode: input.errorCode } : {}),
      lastErrorMessage: input.errorMessage,
      updatedAt: now,
    };

    candidate.status = deriveOperationalStatus(candidate, this.policy);
    await this.repository.saveConnectorSnapshot(candidate);
    await this.ensureIncident(candidate);
    return candidate;
  }

  async enqueueRetry(input: {
    organizationId: string;
    connectorId: string;
    operation: string;
    payload: unknown;
    maxAttempts?: number;
  }): Promise<RetryCommand> {
    const now = this.now();
    const command: RetryCommand = {
      id: randomUUID(),
      organizationId: input.organizationId,
      connectorId: input.connectorId,
      operation: input.operation,
      payload: input.payload,
      attempt: 0,
      maxAttempts: input.maxAttempts ?? 5,
      nextAttemptAt: now,
      status: "PENDING",
      createdAt: now,
      updatedAt: now,
    };
    await this.repository.saveRetry(command);
    return command;
  }

  async processDueRetries(limit = 50): Promise<{
    completed: number;
    rescheduled: number;
    deadLettered: number;
  }> {
    const commands = await this.repository.listDueRetries(this.now(), limit);
    let completed = 0;
    let rescheduled = 0;
    let deadLettered = 0;

    for (const command of commands) {
      command.status = "RUNNING";
      command.updatedAt = this.now();
      await this.repository.saveRetry(command);

      try {
        await this.executor.execute({
          connectorId: command.connectorId,
          operation: command.operation,
          payload: command.payload,
        });
        command.status = "COMPLETED";
        command.updatedAt = this.now();
        await this.repository.saveRetry(command);
        completed++;
      } catch (error) {
        command.attempt++;
        command.lastError =
          error instanceof Error ? error.message : "Unknown connector error";
        command.updatedAt = this.now();

        if (command.attempt >= command.maxAttempts) {
          command.status = "DEAD_LETTER";
          await this.repository.saveRetry(command);
          await this.moveToDeadLetter(command);
          deadLettered++;
        } else {
          command.status = "PENDING";
          const delaySeconds = calculateRetryDelaySeconds(
            command.attempt,
            this.policy,
          );
          command.nextAttemptAt = new Date(
            this.now().getTime() + delaySeconds * 1000,
          );
          await this.repository.saveRetry(command);
          rescheduled++;
        }
      }
    }

    return { completed, rescheduled, deadLettered };
  }

  async acknowledgeIncident(input: {
    incidentId: string;
    actorId: string;
  }): Promise<IntegrationIncident> {
    const incident = await this.repository.getIncident(input.incidentId);
    if (!incident) throw new Error("Integration incident not found");
    incident.status = "ACKNOWLEDGED";
    incident.assignedTo = input.actorId;
    incident.lastObservedAt = this.now();
    await this.repository.saveIncident(incident);
    return incident;
  }

  async resolveIncident(input: {
    incidentId: string;
    actorId: string;
    resolutionNote: string;
  }): Promise<IntegrationIncident> {
    const incident = await this.repository.getIncident(input.incidentId);
    if (!incident) throw new Error("Integration incident not found");
    incident.status = "RESOLVED";
    incident.assignedTo = input.actorId;
    incident.resolutionNote = input.resolutionNote;
    incident.resolvedAt = this.now();
    incident.lastObservedAt = this.now();
    await this.repository.saveIncident(incident);
    return incident;
  }

  async acknowledgeDeadLetter(input: {
    deadLetterId: string;
    actorId: string;
    resolution: string;
  }): Promise<DeadLetterItem> {
    const item = await this.repository.getDeadLetter(input.deadLetterId);
    if (!item) throw new Error("Dead letter item not found");
    item.acknowledgedAt = this.now();
    item.acknowledgedBy = input.actorId;
    item.resolution = input.resolution;
    await this.repository.saveDeadLetter(item);
    return item;
  }

  private async moveToDeadLetter(command: RetryCommand): Promise<void> {
    const item: DeadLetterItem = {
      id: randomUUID(),
      organizationId: command.organizationId,
      connectorId: command.connectorId,
      operation: command.operation,
      payload: command.payload,
      totalAttempts: command.attempt,
      lastError: command.lastError ?? "Unknown connector error",
      failedAt: this.now(),
    };
    await this.repository.saveDeadLetter(item);

    const current =
      await this.repository.getConnectorSnapshot(
        command.organizationId,
        command.connectorId,
      );
    if (current) {
      current.deadLetterCount++;
      current.updatedAt = this.now();
      await this.repository.saveConnectorSnapshot(current);
      await this.ensureIncident(current);
    }
  }

  private async ensureIncident(
    snapshot: ConnectorOperationalSnapshot,
  ): Promise<void> {
    const shouldOpen =
      snapshot.status !== "HEALTHY" ||
      snapshot.deadLetterCount >= this.policy.deadLetterIncidentThreshold;
    if (!shouldOpen) return;

    const incidents =
      await this.repository.listOpenIncidents(snapshot.organizationId);
    const existing = incidents.find(
      (incident) =>
        incident.connectorId === snapshot.connectorId &&
        incident.status !== "RESOLVED",
    );

    const type: IntegrationIncident["type"] = snapshot.reauthRequired
      ? "REAUTH_REQUIRED"
      : snapshot.deadLetterCount >= this.policy.deadLetterIncidentThreshold
        ? "DEAD_LETTER_THRESHOLD"
        : snapshot.status === "FAILED"
          ? "CONNECTOR_FAILED"
          : snapshot.status === "RATE_LIMITED"
            ? "RATE_LIMIT"
            : "CONNECTOR_DEGRADED";

    const now = this.now();
    if (existing) {
      existing.type = type;
      existing.severity = incidentSeverityFor(snapshot);
      existing.lastObservedAt = now;
      existing.occurrenceCount++;
      existing.description =
        snapshot.lastErrorMessage ?? existing.description;
      await this.repository.saveIncident(existing);
      return;
    }

    const incident: IntegrationIncident = {
      id: randomUUID(),
      organizationId: snapshot.organizationId,
      connectorId: snapshot.connectorId,
      severity: incidentSeverityFor(snapshot),
      type,
      status: "OPEN",
      title: `${snapshot.kind} connector requires attention`,
      description:
        snapshot.lastErrorMessage ??
        `Connector status changed to ${snapshot.status}`,
      firstObservedAt: now,
      lastObservedAt: now,
      occurrenceCount: 1,
    };

    await this.repository.saveIncident(incident);
    await this.incidentPublisher.publish({
      organizationId: incident.organizationId,
      ...(incident.connectorId ? { connectorId: incident.connectorId } : {}),
      severity: incident.severity,
      title: incident.title,
      description: incident.description,
      sourceIncidentId: incident.id,
    });
  }
}
