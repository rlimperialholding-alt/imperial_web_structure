import type { TaskApplicationService } from "../application/task-service.js";

export interface WorkerLogger {
  info(data: Record<string, unknown>, message: string): void;
  error(data: Record<string, unknown>, message: string): void;
}

export interface EnforcementWorkerOptions {
  batchSize: number;
  intervalMs: number;
}

export class EnforcementWorker {
  private timer: NodeJS.Timeout | null = null;
  private running = false;

  constructor(
    private readonly service: TaskApplicationService,
    private readonly logger: WorkerLogger,
    private readonly options: EnforcementWorkerOptions = {
      batchSize: 100,
      intervalMs: 60_000,
    },
  ) {}

  start(): void {
    if (this.timer) return;

    this.timer = setInterval(() => {
      void this.tick();
    }, this.options.intervalMs);

    void this.tick();
  }

  async tick(): Promise<number> {
    if (this.running) {
      this.logger.info({}, "Enforcement tick skipped: previous run active");
      return 0;
    }

    this.running = true;
    try {
      const processed = await this.service.runEnforcementBatch(
        this.options.batchSize,
      );
      this.logger.info({ processed }, "Enforcement tick completed");
      return processed;
    } catch (error) {
      this.logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        "Enforcement tick failed",
      );
      throw error;
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
