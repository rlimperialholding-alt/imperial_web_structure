import type { PrismaClient } from "@prisma/client";
import { PrismaAuditRepository } from "./prisma-audit-repository.js";
import { PrismaNotificationOutbox } from "./prisma-notification-outbox.js";
import { PrismaTaskRepository } from "./prisma-task-repository.js";

export interface ItepTransactionContext {
  tasks: PrismaTaskRepository;
  audit: PrismaAuditRepository;
  outbox: PrismaNotificationOutbox;
}

export class PrismaUnitOfWork {
  constructor(private readonly prisma: PrismaClient) {}

  async transaction<T>(
    work: (context: ItepTransactionContext) => Promise<T>,
  ): Promise<T> {
    return this.prisma.$transaction(async (tx) =>
      work({
        tasks: new PrismaTaskRepository(tx),
        audit: new PrismaAuditRepository(tx),
        outbox: new PrismaNotificationOutbox(tx),
      }),
    );
  }
}
