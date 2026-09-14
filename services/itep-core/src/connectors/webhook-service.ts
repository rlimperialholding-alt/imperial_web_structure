import { createHmac, timingSafeEqual } from "node:crypto";
import type { ConnectorSyncOrchestrator } from "./sync-orchestrator.js";

export interface WebhookSubscriptionRepository {
  findByExternalChannelId(
    externalChannelId: string,
  ): Promise<{
    id: string;
    connectorAccountId: string;
    secret: string;
    expiresAt?: Date;
    status: "ACTIVE" | "EXPIRED" | "REVOKED";
  } | null>;

  touch(id: string, occurredAt: Date): Promise<void>;
}

export class ConnectorWebhookService {
  constructor(
    private readonly subscriptions: WebhookSubscriptionRepository,
    private readonly orchestrator: ConnectorSyncOrchestrator,
    private readonly now: () => Date,
  ) {}

  async receive(input: {
    externalChannelId: string;
    rawBody: string;
    signature: string;
  }) {
    const subscription =
      await this.subscriptions.findByExternalChannelId(
        input.externalChannelId,
      );

    if (!subscription || subscription.status !== "ACTIVE") {
      throw new Error("Unknown or inactive webhook subscription");
    }

    if (
      subscription.expiresAt &&
      subscription.expiresAt.getTime() <= this.now().getTime()
    ) {
      throw new Error("Webhook subscription expired");
    }

    if (
      !verifySignature(
        input.rawBody,
        input.signature,
        subscription.secret,
      )
    ) {
      throw new Error("Invalid webhook signature");
    }

    await this.subscriptions.touch(subscription.id, this.now());

    // The webhook is only a wake-up signal. Source data is always fetched
    // from the provider API, then normalized and deduplicated.
    return this.orchestrator.syncAccount(
      subscription.connectorAccountId,
    );
  }
}

export function verifySignature(
  rawBody: string,
  signature: string,
  secret: string,
): boolean {
  const expected = createHmac("sha256", secret)
    .update(rawBody)
    .digest("hex");

  const received = signature.replace(/^sha256=/, "");
  if (expected.length !== received.length) return false;

  return timingSafeEqual(
    Buffer.from(expected, "utf8"),
    Buffer.from(received, "utf8"),
  );
}
