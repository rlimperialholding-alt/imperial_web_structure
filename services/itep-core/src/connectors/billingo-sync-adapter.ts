import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { normalizeBillingoInvoice, type BillingoInvoiceEvent } from "./business-event-normalizers.js";
import type { ConnectorSyncAdapter } from "./ports.js";
export interface BillingoGateway {
  listInvoiceChanges(input: {
    accessToken: string; externalAccountId: string; cursor?: string;
  }): Promise<{ invoices: BillingoInvoiceEvent[]; nextCursor?: string }>;
}
export class BillingoSyncAdapter implements ConnectorSyncAdapter {
  constructor(private readonly gateway: BillingoGateway,
    private readonly ingestion: SourceIngestionService,
    private readonly now: () => Date) {}
  async sync(input: Parameters<ConnectorSyncAdapter["sync"]>[0]) {
    const batch = await this.gateway.listInvoiceChanges({
      accessToken: input.accessToken,
      externalAccountId: input.account.externalAccountId,
      ...(input.checkpoint?.cursor ? { cursor: input.checkpoint.cursor } : {}),
    });
    let ingested=0, ignored=0, failed=0;
    for (const item of batch.invoices) {
      try {
        const result = await this.ingestion.ingest(
          normalizeBillingoInvoice(input.account.organizationId,item,this.now()));
        result.status === "TASK_CREATED" ? ingested++ : ignored++;
      } catch { failed++; }
    }
    return { received: batch.invoices.length, ingested, ignored, failed,
      nextCheckpoint: batch.nextCursor ? {cursor:batch.nextCursor} : {} };
  }
}
