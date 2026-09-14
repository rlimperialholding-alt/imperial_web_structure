import { describe, expect, it } from "vitest";
import type { EmailMessage, EmailSender } from "../src/notifications/email-sender.js";
import {
  OutboxDispatcher,
  type OutboxDispatchRepository,
  type PendingOutboxMessage,
} from "../src/workers/outbox-dispatcher.js";

class MemoryRepo implements OutboxDispatchRepository {
  messages: PendingOutboxMessage[] = [];
  sent: string[] = [];
  failures: Array<{ id: string; attempts: number; next: Date | null }> = [];

  async claimBatch(_now: Date, limit: number) {
    return this.messages.slice(0, limit);
  }
  async markSent(id: string) { this.sent.push(id); }
  async markFailed(id: string, attempts: number, next: Date | null) {
    this.failures.push({ id, attempts, next });
  }
}

class SuccessSender implements EmailSender {
  sent: EmailMessage[] = [];
  async send(message: EmailMessage) {
    this.sent.push(message);
    return { providerMessageId: "gmail-1" };
  }
}

describe("OutboxDispatcher", () => {
  const message: PendingOutboxMessage = {
    id: "outbox-1",
    taskId: "task-1",
    channel: "EMAIL",
    recipient: "employee@example.com",
    cc: [],
    subject: "Reminder",
    body: "Body",
    attempts: 0,
    scheduledFor: new Date("2026-07-24T08:00:00Z"),
    idempotencyKey: "task-1:1",
  };

  it("marks successful messages as sent", async () => {
    const repo = new MemoryRepo();
    repo.messages = [message];
    const sender = new SuccessSender();
    const dispatcher = new OutboxDispatcher(
      repo,
      sender,
      { now: () => new Date("2026-07-24T08:00:00Z") },
    );

    const result = await dispatcher.runOnce();

    expect(result.sent).toBe(1);
    expect(repo.sent).toEqual(["outbox-1"]);
    expect(sender.sent[0]?.headers?.["X-ITEP-Task-Id"]).toBe("task-1");
  });

  it("uses exponential backoff on failure", async () => {
    const repo = new MemoryRepo();
    repo.messages = [message];
    const dispatcher = new OutboxDispatcher(
      repo,
      {
        async send() {
          throw new Error("Temporary Gmail failure");
        },
      },
      { now: () => new Date("2026-07-24T08:00:00Z") },
      { batchSize: 10, maxAttempts: 8, baseBackoffSeconds: 30 },
    );

    const result = await dispatcher.runOnce();

    expect(result.failed).toBe(1);
    expect(repo.failures[0]?.attempts).toBe(1);
    expect(repo.failures[0]?.next).toEqual(
      new Date("2026-07-24T08:00:30Z"),
    );
  });

  it("dead-letters after max attempts", async () => {
    const repo = new MemoryRepo();
    repo.messages = [{ ...message, attempts: 7 }];
    const dispatcher = new OutboxDispatcher(
      repo,
      { async send() { throw new Error("Permanent failure"); } },
      { now: () => new Date("2026-07-24T08:00:00Z") },
      { batchSize: 10, maxAttempts: 8, baseBackoffSeconds: 30 },
    );

    const result = await dispatcher.runOnce();

    expect(result.deadLettered).toBe(1);
    expect(repo.failures[0]?.next).toBeNull();
  });
});
