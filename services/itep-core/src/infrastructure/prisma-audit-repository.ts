import type { Prisma, PrismaClient } from "@prisma/client";
import type { AuditRepository } from "../application/ports.js";
import type { AuditEvent } from "../domain/types.js";

type DbClient = PrismaClient | Prisma.TransactionClient;

export class PrismaAuditRepository implements AuditRepository {
  constructor(private readonly db: DbClient) {}

  async append(event: AuditEvent): Promise<void> {
    const last = await this.db.taskAuditEvent.findFirst({
      where: { taskId: event.taskId },
      orderBy: { sequence: "desc" },
      select: { sequence: true },
    });

    await this.db.taskAuditEvent.create({
      data: {
        id: event.id,
        taskId: event.taskId,
        eventType: event.eventType,
        actorId: event.actorId,
        occurredAt: event.occurredAt,
        payload: event.payload as Prisma.InputJsonValue,
        sequence: (last?.sequence ?? 0n) + 1n,
      },
    });
  }
}
