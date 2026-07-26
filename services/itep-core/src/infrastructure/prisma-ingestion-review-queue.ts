import type { Prisma, PrismaClient } from "@prisma/client";
import type { IngestionReviewQueue } from "../ingestion/ports.js";

export class PrismaIngestionReviewQueue
  implements IngestionReviewQueue {
  constructor(private readonly prisma: PrismaClient) {}

  async enqueue(input: Parameters<IngestionReviewQueue["enqueue"]>[0]) {
    await this.prisma.ingestionReviewItem.create({
      data: {
        sourceEventId: input.event.id,
        organizationId: input.event.organizationId,
        action: input.decision.action,
        reason: input.decision.reason,
        candidate: (input.decision.candidate ?? {}) as Prisma.InputJsonValue,
        status: "OPEN",
        createdAt: input.createdAt,
      },
    });
  }
}
