import type { PrismaClient, Prisma } from "@prisma/client";
import type {
  HumanAnneIncident,
  IncidentSeverity,
} from "../human-anne/types.js";
import type { HumanAnneIncidentRepository } from "../human-anne/incident-service.js";

type DbClient = PrismaClient | Prisma.TransactionClient;

export class PrismaHumanAnneIncidentRepository
  implements HumanAnneIncidentRepository {
  constructor(private readonly db: DbClient) {}

  async create(incident: HumanAnneIncident): Promise<void> {
    await this.db.humanAnneIncident.create({
      data: {
        id: incident.id,
        taskId: incident.taskId ?? null,
        category: incident.category,
        severity: incident.severity,
        status: incident.status,
        title: incident.title,
        description: incident.description,
        recommendedAction: incident.recommendedAction,
        source: incident.source,
        createdAt: incident.createdAt,
        acknowledgedAt: incident.acknowledgedAt ?? null,
        acknowledgedBy: incident.acknowledgedBy ?? null,
        resolvedAt: incident.resolvedAt ?? null,
        resolvedBy: incident.resolvedBy ?? null,
        resolution: incident.resolution ?? null,
      },
    });
  }

  async getById(id: string): Promise<HumanAnneIncident | null> {
    const row = await this.db.humanAnneIncident.findUnique({ where: { id } });
    return row ? this.toDomain(row) : null;
  }

  async listOpen(input: {
    severity?: IncidentSeverity;
    limit: number;
  }): Promise<HumanAnneIncident[]> {
    const rows = await this.db.humanAnneIncident.findMany({
      where: {
        status: { in: ["OPEN", "ACKNOWLEDGED", "IN_PROGRESS"] },
        ...(input.severity ? { severity: input.severity } : {}),
      },
      orderBy: [
        { severity: "desc" },
        { createdAt: "asc" },
      ],
      take: input.limit,
    });
    return rows.map((row) => this.toDomain(row));
  }

  async save(incident: HumanAnneIncident): Promise<void> {
    await this.db.humanAnneIncident.update({
      where: { id: incident.id },
      data: {
        status: incident.status,
        acknowledgedAt: incident.acknowledgedAt ?? null,
        acknowledgedBy: incident.acknowledgedBy ?? null,
        resolvedAt: incident.resolvedAt ?? null,
        resolvedBy: incident.resolvedBy ?? null,
        resolution: incident.resolution ?? null,
      },
    });
  }

  private toDomain(row: any): HumanAnneIncident {
    return {
      id: row.id,
      ...(row.taskId ? { taskId: row.taskId } : {}),
      category: row.category,
      severity: row.severity,
      status: row.status,
      title: row.title,
      description: row.description,
      recommendedAction: row.recommendedAction,
      source: row.source,
      createdAt: row.createdAt,
      ...(row.acknowledgedAt
        ? { acknowledgedAt: row.acknowledgedAt }
        : {}),
      ...(row.acknowledgedBy
        ? { acknowledgedBy: row.acknowledgedBy }
        : {}),
      ...(row.resolvedAt ? { resolvedAt: row.resolvedAt } : {}),
      ...(row.resolvedBy ? { resolvedBy: row.resolvedBy } : {}),
      ...(row.resolution ? { resolution: row.resolution } : {}),
    };
  }
}
