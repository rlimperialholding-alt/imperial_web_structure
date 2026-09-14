import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import {
  normalizeMarketingMetric,
  type MarketingMetricEvent,
} from "./business-event-normalizers.js";
import type { ConnectorSyncAdapter } from "./ports.js";

export interface MetaAdsGateway {
  listCampaignInsights(input: {
    accessToken: string;
    externalAccountId: string;
    cursor?: string;
  }): Promise<{ metrics: MarketingMetricEvent[]; nextCursor?: string }>;
}

export interface GoogleAdsGateway {
  listCampaignInsights(input: {
    accessToken: string;
    externalAccountId: string;
  }): Promise<{ metrics: MarketingMetricEvent[] }>;
}

abstract class MarketingSyncAdapter {
  constructor(
    protected readonly ingestion: SourceIngestionService,
    protected readonly now: () => Date,
  ) {}

  protected async ingest(metrics: MarketingMetricEvent[]) {
    let ingested = 0;
    let ignored = 0;
    let failed = 0;
    for (const metric of metrics) {
      try {
        const result = await this.ingestion.ingest(
          normalizeMarketingMetric(metric.organizationId, metric, this.now()),
        );
        result.status === "TASK_CREATED" ? ingested++ : ignored++;
      } catch {
        failed++;
      }
    }
    return { ingested, ignored, failed };
  }
}

export class MetaAdsSyncAdapter
  extends MarketingSyncAdapter
  implements ConnectorSyncAdapter {
  constructor(
    private readonly gateway: MetaAdsGateway,
    ingestion: SourceIngestionService,
    now: () => Date,
  ) {
    super(ingestion, now);
  }

  async sync(input: Parameters<ConnectorSyncAdapter["sync"]>[0]) {
    const batch = await this.gateway.listCampaignInsights({
      accessToken: input.accessToken,
      externalAccountId: input.account.externalAccountId,
      ...(input.checkpoint?.cursor ? { cursor: input.checkpoint.cursor } : {}),
    });
    const metrics = batch.metrics.map((metric) => ({
      ...metric,
      organizationId: input.account.organizationId,
    }));
    return {
      received: metrics.length,
      ...(await this.ingest(metrics)),
      nextCheckpoint: batch.nextCursor ? { cursor: batch.nextCursor } : {},
    };
  }
}

export class GoogleAdsSyncAdapter
  extends MarketingSyncAdapter
  implements ConnectorSyncAdapter {
  constructor(
    private readonly gateway: GoogleAdsGateway,
    ingestion: SourceIngestionService,
    now: () => Date,
  ) {
    super(ingestion, now);
  }

  async sync(input: Parameters<ConnectorSyncAdapter["sync"]>[0]) {
    const batch = await this.gateway.listCampaignInsights({
      accessToken: input.accessToken,
      externalAccountId: input.account.externalAccountId,
    });
    const metrics = batch.metrics.map((metric) => ({
      ...metric,
      organizationId: input.account.organizationId,
    }));
    return {
      received: metrics.length,
      ...(await this.ingest(metrics)),
      nextCheckpoint: {},
    };
  }
}
