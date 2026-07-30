import { describe, expect, it } from "vitest";
import { SourceIngestionService } from "../src/ingestion/ingestion-service.js";
import {
  IngestionRuleEngine,
  defaultIngestionRules,
} from "../src/ingestion/rules.js";
import { normalizeGmailEvent } from "../src/ingestion/normalizers.js";

describe("SourceIngestionService", () => {
  it("deduplicates the same source event", async () => {
    const stored = new Map<string, any>();
    const service = new SourceIngestionService(
      {
        async findByFingerprint(fp) { return stored.get(fp) ?? null; },
        async findByExternalIdentity(input) {
          return [...stored.values()].find(
            event => event.organizationId === input.organizationId
              && event.source === input.source
              && event.externalId === input.externalId,
          ) ?? null;
        },
        async create(event) { stored.set(event.fingerprint, event); },
        async updateStatus() {},
      },
      new IngestionRuleEngine(defaultIngestionRules()),
      { async findExisting() { return { duplicate: false }; } },
      { async createFromCandidate() { return { taskId: "task-1" }; } },
      { async enqueue() {} },
      { now: () => new Date() },
    );

    const event = normalizeGmailEvent(
      {
        organizationId: "imperial",
        messageId: "m1",
        internalDate: new Date("2026-07-24T08:00:00Z"),
        from: "nav@example.hu",
        to: ["office@example.hu"],
        subject: "NAV határidő",
        bodyText: "Kérjük sürgősen intézni.",
      },
      new Date(),
    );

    const first = await service.ingest(event);
    const second = await service.ingest(event);

    expect(first.status).toBe("TASK_CREATED");
    expect(second.status).toBe("DUPLICATE_EVENT");
  });

  it("treats a concurrent insert race as a duplicate event", async () => {
    const stored = new Map<string, any>();
    let createAttempted = false;
    const service = new SourceIngestionService(
      {
        async findByFingerprint(fp) {
          return createAttempted ? stored.get(fp) ?? null : null;
        },
        async findByExternalIdentity(input) {
          if (!createAttempted) return null;
          return [...stored.values()].find(
            event => event.organizationId === input.organizationId
              && event.source === input.source
              && event.externalId === input.externalId,
          ) ?? null;
        },
        async create(event) {
          createAttempted = true;
          stored.set(event.fingerprint, event);
          throw new Error("unique constraint violation");
        },
        async updateStatus() {},
      },
      new IngestionRuleEngine(defaultIngestionRules()),
      { async findExisting() { return { duplicate: false }; } },
      { async createFromCandidate() { return { taskId: "task-1" }; } },
      { async enqueue() {} },
      { now: () => new Date() },
    );
    const event = normalizeGmailEvent(
      {
        organizationId: "imperial",
        messageId: "concurrent-message",
        internalDate: new Date("2026-07-24T08:00:00Z"),
        from: "sender@example.test",
        to: ["office@example.test"],
        subject: "Párhuzamos feldolgozás",
        bodyText: "Teszt.",
      },
      new Date(),
    );

    const result = await service.ingest(event);

    expect(result.status).toBe("DUPLICATE_EVENT");
    expect(result.reason).toContain("párhuzamos");
  });
});
