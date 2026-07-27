import type { Prisma, PrismaClient } from "@prisma/client";
import type { SourceEventRepository } from "../ingestion/ports.js";
import type {
  SourceEvent,
  SourceEventStatus,
} from "../ingestion/types.js";

export class PrismaSourceEventRepository
  implements SourceEventRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async findByFingerprint(fingerprint: string): Promise<SourceEvent | null> {
    const row = await this.prisma.sourceEvent.findUnique({
      where: { fingerprint },
    });
    return row ? this.toDomain(row) : null;
  }

  async create(event: SourceEvent): Promise<void> {
    await this.prisma.sourceEvent.create({
      data: {
        id: event.id,
        organizationId: event.organizationId,
        ...(event.legalEntityId
          ? { legalEntity: { connect: { id: event.legalEntityId } } }
          : {}),
        source: event.source,
        externalId: event.externalId,
        occurredAt: event.occurredAt,
        receivedAt: event.receivedAt,
        actorId: event.actorId ?? null,
        subject: event.subject ?? null,
        body: event.body ?? null,
        participants: event.participants,
        labels: event.labels,
        metadata: event.metadata as Prisma.InputJsonValue,
        status: event.status,
        fingerprint: event.fingerprint,
      },
    });
  }

  async updateStatus(
    id: string,
    status: SourceEventStatus,
    error?: string,
  ): Promise<void> {
    await this.prisma.sourceEvent.update({
      where: { id },
      data: {
        status,
        lastError: error ?? null,
        processedAt: new Date(),
      },
    });
  }

  private toDomain(row: any): SourceEvent {
    return {
      id: row.id,
      organizationId: row.organizationId,
      ...(row.legalEntityId ? { legalEntityId: row.legalEntityId } : {}),
      source: row.source,
      externalId: row.externalId,
      occurredAt: row.occurredAt,
      receivedAt: row.receivedAt,
      ...(row.actorId ? { actorId: row.actorId } : {}),
      ...(row.subject ? { subject: row.subject } : {}),
      ...(row.body ? { body: row.body } : {}),
      participants: row.participants,
      labels: row.labels,
      metadata: row.metadata ?? {},
      status: row.status,
      fingerprint: row.fingerprint,
    };
  }
}
