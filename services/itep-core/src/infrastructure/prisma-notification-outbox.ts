import type { PrismaClient, Prisma } from "@prisma/client";
import type {
  NotificationMessage,
  NotificationOutbox,
} from "../application/ports.js";

type DbClient = PrismaClient | Prisma.TransactionClient;

export class PrismaNotificationOutbox implements NotificationOutbox {
  constructor(private readonly db: DbClient) {}

  async enqueue(message: NotificationMessage): Promise<void> {
    await this.db.notificationOutbox.upsert({
      where: { idempotencyKey: message.idempotencyKey },
      create: {
        taskId: message.taskId,
        eventKey: message.eventKey,
        channel: message.channel,
        recipient: message.recipient,
        cc: message.cc,
        subject: message.subject,
        body: message.body,
        scheduledFor: message.scheduledFor,
        idempotencyKey: message.idempotencyKey,
      },
      update: {},
    });
  }
}
