import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { normalizeCalendarEvent } from "../ingestion/normalizers.js";
import type { ConnectorSyncAdapter } from "./ports.js";

export interface CalendarChangesGateway {
  listChanges(input: {
    accessToken: string;
    externalAccountId: string;
    syncToken?: string;
  }): Promise<{
    events: Array<{
      eventId: string;
      startAt: Date;
      endAt: Date;
      title: string;
      description?: string;
      organizer: string;
      attendees: string[];
      status: string;
    }>;
    nextSyncToken?: string;
  }>;
}

export class CalendarSyncAdapter implements ConnectorSyncAdapter {
  constructor(
    private readonly gateway: CalendarChangesGateway,
    private readonly ingestion: SourceIngestionService,
    private readonly now: () => Date,
  ) {}

  async sync(input: Parameters<ConnectorSyncAdapter["sync"]>[0]) {
    const batch = await this.gateway.listChanges({
      accessToken: input.accessToken,
      externalAccountId: input.account.externalAccountId,
      ...(input.checkpoint?.syncToken ? { syncToken: input.checkpoint.syncToken } : {}),
    });

    let ingested = 0;
    let ignored = 0;
    let failed = 0;

    for (const event of batch.events) {
      try {
        const result = await this.ingestion.ingest(
          normalizeCalendarEvent(
            {
              organizationId: input.account.organizationId,
              actorId: "digital-anne",
              ...event,
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
      received: batch.events.length,
      ingested,
      ignored,
      failed,
      nextCheckpoint: {
        ...(batch.nextSyncToken ?? input.checkpoint?.syncToken
          ? { syncToken: batch.nextSyncToken ?? input.checkpoint?.syncToken }
          : {}),
      },
    };
  }
}
