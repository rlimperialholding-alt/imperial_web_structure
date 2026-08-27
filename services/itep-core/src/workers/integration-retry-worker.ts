import type { IntegrationControlRoomService } from "../integration-control-room/service.js";

export interface IntegrationRetryWorkerLogger {
  info(data: Record<string, unknown>, message: string): void;
  error(data: Record<string, unknown>, message: string): void;
}

export class IntegrationRetryWorker {
  private timer?: NodeJS.Timeout;
  private running = false;

  constructor(
    private readonly service: IntegrationControlRoomService,
    private readonly intervalMs: number,
    private readonly batchSize = 50,
    private readonly logger: IntegrationRetryWorkerLogger = console,
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
      const result = await this.service.processDueRetries(this.batchSize);
      this.logger.info(result, "Integration retry processing completed");
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        "Integration retry processing failed",
      );
    } finally {
      this.running = false;
    }
  }

  stop(): void {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = undefined;
  }

  async runOnce() {
    return this.service.processDueRetries(this.batchSize);
  }
}
