import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { normalizeGmailEvent } from "../ingestion/normalizers.js";
import type { ConnectorSyncAdapter } from "./ports.js";

export interface GmailHistoryGateway {
  listChanges(input: {
    accessToken: string;
    externalAccountId: string;
    historyId?: string;
  }): Promise<{
    messages: Array<{
      messageId: string;
      threadId?: string;
      internalDate: Date;
      from: string;
      to: string[];
      cc?: string[];
      subject?: string;
      bodyText?: string;
      labels?: string[];
    }>;
    nextHistoryId?: string;
  }>;
}

export class GmailSyncAdapter implements ConnectorSyncAdapter {
  constructor(
    private readonly gateway: GmailHistoryGateway,
    private readonly ingestion: SourceIngestionService,
    private readonly now: () => Date,
  ) {}

  async sync(input: Parameters<ConnectorSyncAdapter["sync"]>[0]) {
    const batch = await this.gateway.listChanges({
      accessToken: input.accessToken,
      externalAccountId: input.account.externalAccountId,
      ...(input.checkpoint?.historyId ? { historyId: input.checkpoint.historyId } : {}),
    });

    let ingested = 0;
    let ignored = 0;
    let failed = 0;

    for (const message of batch.messages) {
      try {
        const result = await this.ingestion.ingest(
          normalizeGmailEvent(
            {
              organizationId: input.account.organizationId,
              actorId: "digital-anne",
              ...message,
            },
            this.now(),
          ),
        );
        if (result.status === "TASK_CREATED") ingested += 1;
        else ignored += 1;
      } catch {
        failed += 1;
      }
    }

    return {
      received: batch.messages.length,
      ingested,
      ignored,
      failed,
      nextCheckpoint: {
        ...(batch.nextHistoryId ?? input.checkpoint?.historyId
          ? { historyId: batch.nextHistoryId ?? input.checkpoint?.historyId }
          : {}),
      },
    };
  }
}
