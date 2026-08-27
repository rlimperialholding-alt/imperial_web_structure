import { describe, expect, it, vi } from "vitest";
import { IntegrationRetryWorker } from "../src/workers/integration-retry-worker.js";

describe("IntegrationRetryWorker", () => {
  it("keeps the worker alive after a transient repository failure", async () => {
    const processDueRetries = vi
      .fn()
      .mockRejectedValueOnce(new Error("database temporarily unavailable"))
      .mockResolvedValueOnce({ processed: 1, failed: 0, deadLettered: 0 });
    const logger = { info: vi.fn(), error: vi.fn() };
    const worker = new IntegrationRetryWorker(
      { processDueRetries } as never,
      60_000,
      25,
      logger,
    );

    await expect(worker.tick()).resolves.toBeUndefined();
    await expect(worker.tick()).resolves.toBeUndefined();

    expect(processDueRetries).toHaveBeenCalledTimes(2);
    expect(logger.error).toHaveBeenCalledWith(
      { error: "database temporarily unavailable" },
      "Integration retry processing failed",
    );
    expect(logger.info).toHaveBeenCalledWith(
      { processed: 1, failed: 0, deadLettered: 0 },
      "Integration retry processing completed",
    );
  });

  it("does not overlap retry batches", async () => {
    let release: (() => void) | undefined;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const processDueRetries = vi.fn(async () => {
      await pending;
      return { processed: 0, failed: 0, deadLettered: 0 };
    });
    const worker = new IntegrationRetryWorker(
      { processDueRetries } as never,
      60_000,
      25,
      { info: vi.fn(), error: vi.fn() },
    );

    const first = worker.tick();
    await worker.tick();
    release?.();
    await first;

    expect(processDueRetries).toHaveBeenCalledTimes(1);
  });
});
