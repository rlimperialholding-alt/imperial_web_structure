import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { buildSourceFingerprint } from "../ingestion/fingerprint.js";
import type { ConnectorSyncAdapter } from "./ports.js";

export interface DriveChangesGateway {
  listChanges(input: { accessToken: string; pageToken?: string }): Promise<{
    changes: Array<{
      fileId: string; removed: boolean; name?: string; mimeType?: string;
      changedAt: Date; createdAt?: Date; parentIds: string[];
      webViewLink?: string; trashed: boolean;
    }>;
    nextPageToken?: string;
  }>;
}

export class DriveSyncAdapter implements ConnectorSyncAdapter {
  constructor(
    private readonly gateway: DriveChangesGateway,
    private readonly ingestion: SourceIngestionService,
    private readonly now: () => Date,
  ) {}

  async sync(input: Parameters<ConnectorSyncAdapter["sync"]>[0]) {
    const batch = await this.gateway.listChanges({
      accessToken: input.accessToken,
      ...(input.checkpoint?.cursor ? { pageToken: input.checkpoint.cursor } : {}),
    });
    let ingested = 0, ignored = 0, failed = 0;
    for (const change of batch.changes) {
      try {
        const occurredAt = change.changedAt;
        const result = await this.ingestion.ingest({
          id: `SRC-DRIVE-${change.fileId}-${occurredAt.getTime()}`,
          organizationId: input.account.organizationId,
          source: "DRIVE",
          externalId: `${change.fileId}:${occurredAt.toISOString()}`,
          occurredAt,
          receivedAt: this.now(),
          actorId: "digital-anne",
          subject: change.removed ? `Drive fájl eltávolítva: ${change.fileId}` : `Drive fájl változott: ${change.name ?? change.fileId}`,
          ...(change.webViewLink ? { body: change.webViewLink } : {}),
          participants: [],
          labels: [change.mimeType ?? "unknown", change.removed ? "removed" : "changed"],
          metadata: {
            fileId: change.fileId, name: change.name, mimeType: change.mimeType,
            parentIds: change.parentIds, webViewLink: change.webViewLink,
            removed: change.removed, trashed: change.trashed,
          },
          status: "NORMALIZED",
          fingerprint: buildSourceFingerprint({
            organizationId: input.account.organizationId,
            source: "DRIVE",
            externalId: `${change.fileId}:${occurredAt.toISOString()}`,
            ...(change.name ? { subject: change.name } : {}),
            occurredAt,
          }),
        });
        if (result.status === "TASK_CREATED") ingested++; else ignored++;
      } catch { failed++; }
    }
    return { received: batch.changes.length, ingested, ignored, failed,
      nextCheckpoint: {
        ...(batch.nextPageToken ?? input.checkpoint?.cursor
          ? { cursor: batch.nextPageToken ?? input.checkpoint?.cursor }
          : {}),
      } };
  }
}
