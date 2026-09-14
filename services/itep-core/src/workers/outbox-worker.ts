import type { OutboxDispatcher } from "./outbox-dispatcher.js";

export interface OutboxWorkerLogger {
  info(data: Record<string, unknown>, message: string): void;
  error(data: Record<string, unknown>, message: string): void;
}

export class OutboxWorker {
  private timer: NodeJS.Timeout | null = null;
  private running = false;

  constructor(
    private readonly dispatcher: OutboxDispatcher,
    private readonly logger: OutboxWorkerLogger,
    private readonly intervalMs = 15_000,
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
      const result = await this.dispatcher.runOnce();
      this.logger.info(result, "Outbox dispatch completed");
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        "Outbox dispatch failed",
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
