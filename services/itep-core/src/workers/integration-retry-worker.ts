import type { IntegrationControlRoomService } from "../integration-control-room/service.js";

export class IntegrationRetryWorker {
  private timer?: NodeJS.Timeout;

  constructor(
    private readonly service: IntegrationControlRoomService,
    private readonly intervalMs: number,
    private readonly batchSize = 50,
  ) {}

  start(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      void this.service.processDueRetries(this.batchSize);
    }, this.intervalMs);
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
