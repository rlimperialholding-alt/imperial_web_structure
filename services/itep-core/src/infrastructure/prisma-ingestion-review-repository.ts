import type { Prisma, PrismaClient } from "@prisma/client";
import type {
  IngestionReviewItem,
  IngestionReviewRepository,
} from "../ingestion/review-service.js";

export class PrismaIngestionReviewRepository
  implements IngestionReviewRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async getById(id: string): Promise<IngestionReviewItem | null> {
    const row = await this.prisma.ingestionReviewItem.findUnique({
      where: { id },
    });
    return row ? map(row) : null;
  }

  async listOpen(
    organizationId: string,
    limit: number,
  ): Promise<IngestionReviewItem[]> {
    const rows = await this.prisma.ingestionReviewItem.findMany({
      where: { organizationId, status: "OPEN" },
      orderBy: { createdAt: "asc" },
      take: limit,
    });
    return rows.map(map);
  }

  async save(item: IngestionReviewItem): Promise<void> {
    await this.prisma.ingestionReviewItem.update({
      where: { id: item.id },
      data: {
        candidate: item.candidate as unknown as Prisma.InputJsonValue,
        status: item.status,
        reviewedAt: item.reviewedAt ?? null,
        reviewedBy: item.reviewedBy ?? null,
        resolution: item.resolution ?? null,
      },
    });
  }
}

function map(row: any): IngestionReviewItem {
  return {
    id: row.id,
    organizationId: row.organizationId,
    sourceEventId: row.sourceEventId,
    candidate: row.candidate,
    status: row.status,
    createdAt: row.createdAt,
    ...(row.reviewedAt ? { reviewedAt: row.reviewedAt } : {}),
    ...(row.reviewedBy ? { reviewedBy: row.reviewedBy } : {}),
    ...(row.resolution ? { resolution: row.resolution } : {}),
  };
}
