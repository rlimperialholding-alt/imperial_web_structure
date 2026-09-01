import type { Prisma, PrismaClient } from "@prisma/client";
import type { TaskRepository } from "../application/ports.js";
import type {
  EvidenceSubmission,
  Task,
} from "../domain/types.js";

type DbClient = PrismaClient | Prisma.TransactionClient;

export class PrismaTaskRepository implements TaskRepository {
  constructor(private readonly db: DbClient) {}

  async getById(id: string): Promise<Task | null> {
    const row = await this.db.itepTask.findUnique({
      where: { id },
      include: {
        evidence: { orderBy: { submittedAt: "asc" } },
        dependenciesFrom: true,
      },
    });
    return row ? this.toDomain(row) : null;
  }

  async create(task: Task): Promise<void> {
    await this.db.itepTask.create({
      data: this.toCreateData(task),
    });
  }

  async save(task: Task, expectedVersion?: number): Promise<void> {
    const where = expectedVersion === undefined
      ? { id: task.id }
      : { id: task.id, version: expectedVersion };

    const result = await this.db.itepTask.updateMany({
      where,
      data: {
        title: task.title,
        description: task.description,
        priority: task.priority,
        status: task.status,
        dueAt: task.dueAt,
        acceptanceCriteria: task.acceptanceCriteria,
        evidenceType: task.evidenceRequirement.type,
        evidenceDescription: task.evidenceRequirement.description,
        machineVerifiable: task.evidenceRequirement.machineVerifiable,
        escalationPersonId: task.escalationPersonId,
        contactEmail: task.contact.email,
        contactPhone: task.contact.phone ?? null,
        lastCheckedAt: task.lastCheckedAt ?? null,
        nextCheckAt: task.nextCheckAt,
        reminderLevel: task.reminderLevel,
        acceptedBy: task.acceptedBy ?? null,
        acceptedAt: task.acceptedAt ?? null,
        rejectionReason: task.rejectionReason ?? null,
        blockedReason: task.blockedReason ?? null,
        cancelledReason: task.cancelledReason ?? null,
        sensitivity: task.sensitivity,
        version: { increment: 1 },
      },
    });

    if (result.count !== 1) {
      throw new Error(`Optimistic concurrency conflict for task ${task.id}`);
    }

    const existingEvidence = await this.db.taskEvidence.findMany({
      where: { taskId: task.id },
      select: { id: true },
    });
    const existingIds = new Set(existingEvidence.map((x) => x.id));
    const newEvidence = task.evidenceSubmissions.filter(
      (item) => !existingIds.has(item.id),
    );

    if (newEvidence.length > 0) {
      await this.db.taskEvidence.createMany({
        data: newEvidence.map((item) => ({
          id: item.id,
          taskId: task.id,
          type: item.type,
          uri: item.uri,
          submittedAt: item.submittedAt,
          submittedBy: item.submittedBy,
          checksum: item.checksum ?? null,
          metadata: item.metadata as Prisma.InputJsonValue | undefined,
        })),
      });
    }
  }

  async findDueForCheck(now: Date, limit: number): Promise<Task[]> {
    const rows = await this.db.itepTask.findMany({
      where: {
        nextCheckAt: { lte: now },
        status: { notIn: ["CLOSED", "CANCELLED"] },
      },
      include: {
        evidence: { orderBy: { submittedAt: "asc" } },
        dependenciesFrom: true,
      },
      orderBy: [{ priority: "asc" }, { nextCheckAt: "asc" }],
      take: limit,
    });
    return rows.map((row) => this.toDomain(row));
  }

  async hasOpenDependencies(taskId: string): Promise<boolean> {
    const count = await this.db.taskDependency.count({
      where: {
        taskId,
        dependsOn: {
          status: { notIn: ["CLOSED", "CANCELLED"] },
        },
      },
    });
    return count > 0;
  }

  private toCreateData(task: Task): Prisma.ItepTaskCreateInput {
    return {
      id: task.id,
      organizationId: task.organizationId,
      source: task.source,
      sourceExternalId: task.sourceExternalId ?? null,
      semanticFingerprint: task.semanticFingerprint ?? null,
      issuerId: task.issuerId,
      assigneeId: task.assigneeId,
      assigneeType: task.assigneeType,
      title: task.title,
      description: task.description,
      priority: task.priority,
      status: task.status,
      createdAt: task.createdAt,
      dueAt: task.dueAt,
      acceptanceCriteria: task.acceptanceCriteria,
      evidenceType: task.evidenceRequirement.type,
      evidenceDescription: task.evidenceRequirement.description,
      machineVerifiable: task.evidenceRequirement.machineVerifiable,
      escalationPersonId: task.escalationPersonId,
      contactEmail: task.contact.email,
      contactPhone: task.contact.phone ?? null,
      lastCheckedAt: task.lastCheckedAt ?? null,
      nextCheckAt: task.nextCheckAt,
      reminderLevel: task.reminderLevel,
      acceptedBy: task.acceptedBy ?? null,
      acceptedAt: task.acceptedAt ?? null,
      rejectionReason: task.rejectionReason ?? null,
      blockedReason: task.blockedReason ?? null,
      cancelledReason: task.cancelledReason ?? null,
      sensitivity: task.sensitivity,
      evidence: {
        create: task.evidenceSubmissions.map((item) => ({
          id: item.id,
          type: item.type,
          uri: item.uri,
          submittedAt: item.submittedAt,
          submittedBy: item.submittedBy,
          checksum: item.checksum ?? null,
          metadata: item.metadata as Prisma.InputJsonValue | undefined,
        })),
      },
    };
  }

  private toDomain(row: any): Task {
    return {
      id: row.id,
      organizationId: row.organizationId,
      source: row.source,
      ...(row.sourceExternalId ? { sourceExternalId: row.sourceExternalId } : {}),
      ...(row.semanticFingerprint ? { semanticFingerprint: row.semanticFingerprint } : {}),
      issuerId: row.issuerId,
      assigneeId: row.assigneeId,
      assigneeType: row.assigneeType,
      title: row.title,
      description: row.description,
      priority: row.priority,
      createdAt: row.createdAt,
      dueAt: row.dueAt,
      acceptanceCriteria: row.acceptanceCriteria,
      evidenceRequirement: {
        type: row.evidenceType,
        description: row.evidenceDescription,
        machineVerifiable: row.machineVerifiable,
      },
      evidenceSubmissions: row.evidence.map(
        (item: any): EvidenceSubmission => ({
          id: item.id,
          type: item.type,
          uri: item.uri,
          submittedAt: item.submittedAt,
          submittedBy: item.submittedBy,
          ...(item.checksum ? { checksum: item.checksum } : {}),
          ...(item.metadata ? { metadata: item.metadata } : {}),
        }),
      ),
      escalationPersonId: row.escalationPersonId,
      contact: {
        email: row.contactEmail,
        ...(row.contactPhone ? { phone: row.contactPhone } : {}),
      },
      status: row.status,
      ...(row.lastCheckedAt ? { lastCheckedAt: row.lastCheckedAt } : {}),
      nextCheckAt: row.nextCheckAt,
      reminderLevel: row.reminderLevel,
      relatedEntityIds: [],
      dependencies: row.dependenciesFrom.map((d: any) => d.dependsOnId),
      sensitivity: row.sensitivity,
      ...(row.acceptedBy ? { acceptedBy: row.acceptedBy } : {}),
      ...(row.acceptedAt ? { acceptedAt: row.acceptedAt } : {}),
      ...(row.rejectionReason ? { rejectionReason: row.rejectionReason } : {}),
      ...(row.blockedReason ? { blockedReason: row.blockedReason } : {}),
      ...(row.cancelledReason ? { cancelledReason: row.cancelledReason } : {}),
    };
  }
}
