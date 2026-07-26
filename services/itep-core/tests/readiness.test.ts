import { describe, expect, it } from "vitest";
import { ReadinessAggregator } from "../src/operations/readiness.js";

describe("ReadinessAggregator", () => {
  it("allows non-critical degraded dependencies", async () => {
    const result = await new ReadinessAggregator([
      {
        name: "database",
        critical: true,
        async check() { return { ok: true }; },
      },
      {
        name: "gmail",
        critical: false,
        async check() { return { ok: false, details: "reauth required" }; },
      },
    ]).inspect();

    expect(result.ready).toBe(true);
  });

  it("fails when a critical dependency is down", async () => {
    const result = await new ReadinessAggregator([
      {
        name: "database",
        critical: true,
        async check() { return { ok: false }; },
      },
    ]).inspect();

    expect(result.ready).toBe(false);
  });
});
