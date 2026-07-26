import type { PrismaClient } from "@prisma/client";
import type { WebhookSubscriptionRepository } from "../connectors/webhook-service.js";

export class PrismaWebhookSubscriptionRepository
  implements WebhookSubscriptionRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async findByExternalChannelId(externalChannelId: string) {
    const row = await this.prisma.webhookSubscription.findUnique({
      where: { externalChannelId },
      select: {
        id: true,
        connectorAccountId: true,
        secret: true,
        expiresAt: true,
        status: true,
      },
    });
    if (!row) return null;
    return {
      id: row.id,
      connectorAccountId: row.connectorAccountId,
      secret: row.secret,
      status: row.status,
      ...(row.expiresAt ? { expiresAt: row.expiresAt } : {}),
    };
  }

  async touch(id: string, occurredAt: Date): Promise<void> {
    await this.prisma.webhookSubscription.update({
      where: { id },
      data: { lastNotificationAt: occurredAt },
    });
  }
}
