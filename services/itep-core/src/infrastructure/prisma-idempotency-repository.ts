import type { PrismaClient } from "@prisma/client";
import type {
  IdempotencyRecord,
  IdempotencyRepository,
} from "../security/idempotency.js";

export class PrismaIdempotencyRepository
  implements IdempotencyRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async get(scope: string, key: string): Promise<IdempotencyRecord | null> {
    const row = await this.prisma.idempotencyRecord.findUnique({
      where: { scope_key: { scope, key } },
    });
    if (!row || row.expiresAt <= new Date()) return null;
    return {
      key: row.key,
      scope: row.scope,
      requestHash: row.requestHash,
      ...(row.responseStatus !== null
        ? { responseStatus: row.responseStatus }
        : {}),
      ...(row.responseBody !== null
        ? { responseBody: row.responseBody }
        : {}),
      createdAt: row.createdAt,
      expiresAt: row.expiresAt,
      ...(row.completedAt ? { completedAt: row.completedAt } : {}),
    };
  }

  async create(record: IdempotencyRecord): Promise<void> {
    await this.prisma.idempotencyRecord.create({
      data: {
        key: record.key,
        scope: record.scope,
        requestHash: record.requestHash,
        createdAt: record.createdAt,
        expiresAt: record.expiresAt,
      },
    });
  }

  async complete(input: {
    scope: string;
    key: string;
    responseStatus: number;
    responseBody: unknown;
    completedAt: Date;
  }): Promise<void> {
    await this.prisma.idempotencyRecord.update({
      where: { scope_key: { scope: input.scope, key: input.key } },
      data: {
        responseStatus: input.responseStatus,
        responseBody: input.responseBody as any,
        completedAt: input.completedAt,
      },
    });
  }
}
