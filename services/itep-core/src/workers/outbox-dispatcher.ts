import type { EmailSender } from "../notifications/email-sender.js";

export interface PendingOutboxMessage {
  id: string;
  taskId: string;
  channel: string;
  recipient: string;
  cc: string[];
  subject: string;
  body: string;
  htmlBody?: string;
  attempts: number;
  scheduledFor: Date;
  idempotencyKey: string;
}

export interface OutboxDispatchRepository {
  claimBatch(now: Date, limit: number): Promise<PendingOutboxMessage[]>;
  markSent(
    id: string,
    sentAt: Date,
    providerMessageId: string,
  ): Promise<void>;
  markFailed(
    id: string,
    attempts: number,
    nextAttemptAt: Date | null,
    error: string,
  ): Promise<void>;
}

export interface DispatcherClock {
  now(): Date;
}

export interface OutboxDispatcherOptions {
  batchSize: number;
  maxAttempts: number;
  baseBackoffSeconds: number;
}

export class OutboxDispatcher {
  constructor(
    private readonly repository: OutboxDispatchRepository,
    private readonly email: EmailSender,
    private readonly clock: DispatcherClock,
    private readonly options: OutboxDispatcherOptions = {
      batchSize: 50,
      maxAttempts: 8,
      baseBackoffSeconds: 30,
    },
  ) {}

  async runOnce(): Promise<{
    claimed: number;
    sent: number;
    failed: number;
    deadLettered: number;
  }> {
    const now = this.clock.now();
    const messages = await this.repository.claimBatch(
      now,
      this.options.batchSize,
    );

    let sent = 0;
    let failed = 0;
    let deadLettered = 0;

    for (const message of messages) {
      try {
        if (message.channel !== "EMAIL") {
          throw new Error(`Unsupported channel: ${message.channel}`);
        }

        const result = await this.email.send({
          to: message.recipient,
          cc: message.cc,
          subject: message.subject,
          text: message.body,
          ...(message.htmlBody ? { html: message.htmlBody } : {}),
          headers: {
            "X-ITEP-Task-Id": message.taskId,
            "X-ITEP-Idempotency-Key": message.idempotencyKey,
          },
        });

        await this.repository.markSent(
          message.id,
          this.clock.now(),
          result.providerMessageId,
        );
        sent += 1;
      } catch (error) {
        const attempts = message.attempts + 1;
        const messageText =
          error instanceof Error ? error.message : "Unknown outbox error";

        if (attempts >= this.options.maxAttempts) {
          await this.repository.markFailed(
            message.id,
            attempts,
            null,
            messageText,
          );
          deadLettered += 1;
        } else {
          await this.repository.markFailed(
            message.id,
            attempts,
            this.nextAttemptAt(this.clock.now(), attempts),
            messageText,
          );
          failed += 1;
        }
      }
    }

    return {
      claimed: messages.length,
      sent,
      failed,
      deadLettered,
    };
  }

  private nextAttemptAt(now: Date, attempts: number): Date {
    const seconds =
      this.options.baseBackoffSeconds * 2 ** Math.max(0, attempts - 1);
    return new Date(now.getTime() + seconds * 1000);
  }
}
