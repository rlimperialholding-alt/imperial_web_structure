import type { PrismaClient } from "@prisma/client";
import type {
  ConnectorOperationalSnapshot,
  DeadLetterItem,
  IntegrationIncident,
  RetryCommand,
} from "../integration-control-room/domain.js";
import type { IntegrationControlRoomRepository } from "../integration-control-room/ports.js";

export class PrismaIntegrationControlRoomRepository
  implements IntegrationControlRoomRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async listConnectorSnapshots(organizationId: string) {
    return (await this.prisma.connectorOperationalSnapshot.findMany({
      where: { organizationId },
      orderBy: [{ status: "asc" }, { updatedAt: "desc" }],
    })) as ConnectorOperationalSnapshot[];
  }

  async getConnectorSnapshot(organizationId: string, connectorId: string) {
    return (await this.prisma.connectorOperationalSnapshot.findUnique({
      where: {
        organizationId_connectorId: { organizationId, connectorId },
      },
    })) as ConnectorOperationalSnapshot | null;
  }

  async saveConnectorSnapshot(snapshot: ConnectorOperationalSnapshot) {
    await this.prisma.connectorOperationalSnapshot.upsert({
      where: {
        organizationId_connectorId: {
          organizationId: snapshot.organizationId,
          connectorId: snapshot.connectorId,
        },
      },
      create: snapshot as any,
      update: snapshot as any,
    });
  }

  async listOpenIncidents(organizationId: string) {
    return (await this.prisma.integrationIncident.findMany({
      where: { organizationId, status: { not: "RESOLVED" } },
      orderBy: [{ severity: "desc" }, { lastObservedAt: "desc" }],
    })) as IntegrationIncident[];
  }

  async getIncident(id: string) {
    return (await this.prisma.integrationIncident.findUnique({
      where: { id },
    })) as IntegrationIncident | null;
  }

  async saveIncident(incident: IntegrationIncident) {
    await this.prisma.integrationIncident.upsert({
      where: { id: incident.id },
      create: incident as any,
      update: incident as any,
    });
  }

  async listDueRetries(now: Date, limit: number) {
    return (await this.prisma.connectorRetryCommand.findMany({
      where: { status: "PENDING", nextAttemptAt: { lte: now } },
      orderBy: { nextAttemptAt: "asc" },
      take: limit,
    })) as RetryCommand[];
  }

  async getRetry(id: string) {
    return (await this.prisma.connectorRetryCommand.findUnique({
      where: { id },
    })) as RetryCommand | null;
  }

  async saveRetry(command: RetryCommand) {
    await this.prisma.connectorRetryCommand.upsert({
      where: { id: command.id },
      create: command as any,
      update: command as any,
    });
  }

  async listDeadLetters(organizationId: string) {
    return (await this.prisma.connectorDeadLetterItem.findMany({
      where: { organizationId },
      orderBy: { failedAt: "desc" },
    })) as DeadLetterItem[];
  }

  async getDeadLetter(id: string) {
    return (await this.prisma.connectorDeadLetterItem.findUnique({
      where: { id },
    })) as DeadLetterItem | null;
  }

  async saveDeadLetter(item: DeadLetterItem) {
    await this.prisma.connectorDeadLetterItem.upsert({
      where: { id: item.id },
      create: item as any,
      update: item as any,
    });
  }
}
