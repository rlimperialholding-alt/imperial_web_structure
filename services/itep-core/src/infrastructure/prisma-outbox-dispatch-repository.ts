import type { PrismaClient } from "@prisma/client";
import type {
  OutboxDispatchRepository,
  PendingOutboxMessage,
} from "../workers/outbox-dispatcher.js";

export class PrismaOutboxDispatchRepository
  implements OutboxDispatchRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async claimBatch(now: Date, limit: number): Promise<PendingOutboxMessage[]> {
    return this.prisma.$transaction(async (tx) => {
      const rows = await tx.$queryRaw<Array<{
        id: string;
        taskId: string;
        channel: string;
        recipient: string;
        cc: string[];
        subject: string;
        body: string;
        attempts: number;
        scheduledFor: Date;
        idempotencyKey: string;
      }>>`
        SELECT *
        FROM "NotificationOutbox"
        WHERE "sentAt" IS NULL
          AND "scheduledFor" <= ${now}
          AND "lockedAt" IS NULL
        ORDER BY "scheduledFor" ASC
        FOR UPDATE SKIP LOCKED
        LIMIT ${limit}
      `;

      if (rows.length > 0) {
        await tx.notificationOutbox.updateMany({
          where: { id: { in: rows.map((row) => row.id) } },
          data: { lockedAt: now },
        });
      }

      return rows;
    });
  }

  async markSent(
    id: string,
    sentAt: Date,
    providerMessageId: string,
  ): Promise<void> {
    await this.prisma.notificationOutbox.update({
      where: { id },
      data: {
        sentAt,
        providerMessageId,
        lockedAt: null,
        lastError: null,
      },
    });
  }

  async markFailed(
    id: string,
    attempts: number,
    nextAttemptAt: Date | null,
    error: string,
  ): Promise<void> {
    await this.prisma.notificationOutbox.update({
      where: { id },
      data: {
        attempts,
        scheduledFor: nextAttemptAt ?? new Date("9999-12-31T00:00:00.000Z"),
        lockedAt: null,
        lastError: error.slice(0, 2000),
        deadLetteredAt: nextAttemptAt === null ? new Date() : null,
      },
    });
  }
}
