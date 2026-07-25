import type { PrismaClient } from "@prisma/client";
import type { ExistingTaskLookup } from "../ingestion/deduplicator.js";

export class PrismaIngestionDedupLookup
  implements ExistingTaskLookup {
  constructor(private readonly prisma: PrismaClient) {}

  async findBySource(input: {
    organizationId: string;
    source: string;
    sourceExternalId: string;
  }) {
    return this.prisma.itepTask.findFirst({
      where: {
        organizationId: input.organizationId,
        source: input.source,
        sourceExternalId: input.sourceExternalId,
      },
      select: { id: true },
    });
  }

  async findBySemanticFingerprint(fingerprint: string) {
    return this.prisma.itepTask.findFirst({
      where: {
        semanticFingerprint: fingerprint,
        status: { notIn: ["CLOSED", "CANCELLED"] },
      },
      select: { id: true },
    });
  }
}
