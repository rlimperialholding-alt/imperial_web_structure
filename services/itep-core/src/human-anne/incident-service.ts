import type { Clock, IdGenerator } from "../application/ports.js";
import type {
  HumanAnneIncident,
  IncidentSeverity,
  IncidentStatus,
} from "./types.js";

export interface HumanAnneIncidentRepository {
  create(incident: HumanAnneIncident): Promise<void>;
  getById(id: string): Promise<HumanAnneIncident | null>;
  listOpen(input: {
    severity?: IncidentSeverity;
    limit: number;
  }): Promise<HumanAnneIncident[]>;
  save(incident: HumanAnneIncident): Promise<void>;
}

export class HumanAnneIncidentService {
  constructor(
    private readonly repository: HumanAnneIncidentRepository,
    private readonly clock: Clock,
    private readonly ids: IdGenerator,
  ) {}

  async open(input: {
    taskId?: string;
    category: string;
    severity: IncidentSeverity;
    title: string;
    description: string;
    recommendedAction: string;
    source: string;
    createdAt?: Date;
  }): Promise<HumanAnneIncident> {
    const incident: HumanAnneIncident = {
      id: this.ids.next(),
      ...(input.taskId ? { taskId: input.taskId } : {}),
      category: input.category,
      severity: input.severity,
      status: "OPEN",
      title: input.title,
      description: input.description,
      recommendedAction: input.recommendedAction,
      source: input.source,
      createdAt: input.createdAt ?? this.clock.now(),
    };
    await this.repository.create(incident);
    return incident;
  }

  async acknowledge(
    id: string,
    actorId: string,
  ): Promise<HumanAnneIncident> {
    const incident = await this.requireIncident(id);
    if (incident.status !== "OPEN") {
      throw new Error("Only open incidents can be acknowledged");
    }
    const changed: HumanAnneIncident = {
      ...incident,
      status: "ACKNOWLEDGED",
      acknowledgedAt: this.clock.now(),
      acknowledgedBy: actorId,
    };
    await this.repository.save(changed);
    return changed;
  }

  async resolve(
    id: string,
    actorId: string,
    resolution: string,
  ): Promise<HumanAnneIncident> {
    if (!resolution.trim()) {
      throw new Error("Resolution is required");
    }
    const incident = await this.requireIncident(id);
    if (["RESOLVED", "DISMISSED"].includes(incident.status)) {
      throw new Error("Incident is already closed");
    }
    const changed: HumanAnneIncident = {
      ...incident,
      status: "RESOLVED",
      resolvedAt: this.clock.now(),
      resolvedBy: actorId,
      resolution,
    };
    await this.repository.save(changed);
    return changed;
  }

  async changeStatus(
    id: string,
    status: Exclude<IncidentStatus, "RESOLVED">,
    actorId: string,
  ): Promise<HumanAnneIncident> {
    const incident = await this.requireIncident(id);
    const changed: HumanAnneIncident = {
      ...incident,
      status,
      ...(status === "ACKNOWLEDGED"
        ? {
            acknowledgedAt: this.clock.now(),
            acknowledgedBy: actorId,
          }
        : {}),
    };
    await this.repository.save(changed);
    return changed;
  }

  listOpen(severity?: IncidentSeverity, limit = 100) {
    return this.repository.listOpen({ severity, limit });
  }

  private async requireIncident(id: string): Promise<HumanAnneIncident> {
    const incident = await this.repository.getById(id);
    if (!incident) throw new Error(`Incident not found: ${id}`);
    return incident;
  }
}
