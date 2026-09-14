import type { ConnectorSyncOrchestrator } from "../connectors/sync-orchestrator.js";

export interface ConnectorWorkerLogger {
  info(data: Record<string, unknown>, message: string): void;
  error(data: Record<string, unknown>, message: string): void;
}

export class ConnectorSyncWorker {
  private timer: NodeJS.Timeout | null = null;
  private running = false;

  constructor(
    private readonly orchestrator: ConnectorSyncOrchestrator,
    private readonly logger: ConnectorWorkerLogger,
    private readonly intervalMs = 60_000,
  ) {}

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => void this.tick(), this.intervalMs);
    void this.tick();
  }

  async tick(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      const results = await this.orchestrator.syncAll();
      const failed = results.filter((item) => !item.ok).length;
      this.logger.info(
        { accounts: results.length, failed },
        "Connector synchronization completed",
      );
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        "Connector synchronization failed",
      );
    } finally {
      this.running = false;
    }
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
