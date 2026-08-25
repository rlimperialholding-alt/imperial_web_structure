import { describe, expect, it } from "vitest";
import { BasicAuthorizationService } from "../src/application/basic-authorization.js";
import { TaskApplicationService } from "../src/application/task-service.js";
import type {
  ActorContext,
  AuditRepository,
  Clock,
  IdGenerator,
  NotificationMessage,
  NotificationOutbox,
  TaskRepository,
} from "../src/application/ports.js";
import type { AuditEvent, Task } from "../src/domain/types.js";
import { makeTask } from "./fixtures.js";

class MemoryTaskRepository implements TaskRepository {
  readonly items = new Map<string, Task>();
  async getById(id: string) { return this.items.get(id) ?? null; }
  async create(task: Task) { this.items.set(task.id, task); }
  async save(task: Task) { this.items.set(task.id, task); }
  async findDueForCheck(now: Date, limit: number) {
    return [...this.items.values()]
      .filter((t) =>
        !["CLOSED", "CANCELLED"].includes(t.status) &&
        t.nextCheckAt.getTime() <= now.getTime()
      )
      .slice(0, limit);
  }
  async hasOpenDependencies() { return false; }
}

class MemoryAudit implements AuditRepository {
  readonly events: AuditEvent[] = [];
  async append(event: AuditEvent) { this.events.push(event); }
}

class MemoryOutbox implements NotificationOutbox {
  readonly messages: NotificationMessage[] = [];
  async enqueue(message: NotificationMessage) {
    if (!this.messages.some((x) => x.idempotencyKey === message.idempotencyKey)) {
      this.messages.push(message);
    }
  }
}

const actor: ActorContext = {
  actorId: "director-1",
  organizationId: "imperial-holding",
  roles: ["DIRECTOR"],
  permissions: [
    "task.create",
    "task.read.all",
    "task.transition.all",
    "task.accept",
    "task.accept.all",
  ],
};

describe("TaskApplicationService", () => {
  it("creates a task with audit event and calculated check date", async () => {
    const tasks = new MemoryTaskRepository();
    const audit = new MemoryAudit();
    const outbox = new MemoryOutbox();
    const service = new TaskApplicationService(
      tasks,
      audit,
      outbox,
      new BasicAuthorizationService(),
      { now: () => new Date("2026-07-24T08:00:00.000Z") },
      { next: () => "ITEP-100" },
    );

    const base = makeTask();
    const created = await service.create(actor, {
      organizationId: base.organizationId,
      source: base.source,
      issuerId: base.issuerId,
      assigneeId: base.assigneeId,
      assigneeType: base.assigneeType,
      title: base.title,
      description: base.description,
      priority: base.priority,
      dueAt: base.dueAt,
      acceptanceCriteria: base.acceptanceCriteria,
      evidenceRequirement: base.evidenceRequirement,
      escalationPersonId: base.escalationPersonId,
      contact: base.contact,
      relatedEntityIds: [],
      dependencies: [],
      sensitivity: base.sensitivity,
    });

    expect(created.id).toBe("ITEP-100");
    expect(audit.events[0]?.eventType).toBe("TASK_CREATED");
  });

  it("queues overdue P1 escalation with an idempotency key", async () => {
    const tasks = new MemoryTaskRepository();
    const audit = new MemoryAudit();
    const outbox = new MemoryOutbox();
    const overdue = makeTask({
      nextCheckAt: new Date("2026-07-23T08:00:00.000Z"),
      dueAt: new Date("2026-07-20T08:00:00.000Z"),
    });
    tasks.items.set(overdue.id, overdue);

    const service = new TaskApplicationService(
      tasks,
      audit,
      outbox,
      new BasicAuthorizationService(),
      { now: () => new Date("2026-07-24T08:00:00.000Z") },
      { next: () => "generated-id" },
    );

    const count = await service.runEnforcementBatch();
    expect(count).toBe(1);
    expect(outbox.messages).toHaveLength(1);
    expect(outbox.messages[0]?.eventKey).toBe("P1_ESCALATION");
    expect(outbox.messages[0]?.cc).toEqual(["manager-1"]);
  });

  it("blocks an unknown-brand reminder without starving later tasks", async () => {
    const tasks = new MemoryTaskRepository();
    const audit = new MemoryAudit();
    const outbox = new MemoryOutbox();
    const due = new Date("2026-07-23T08:00:00.000Z");
    tasks.items.set("UNKNOWN", makeTask({ id: "UNKNOWN", organizationId: "unknown-brand", nextCheckAt: due }));
    tasks.items.set("VALID", makeTask({ id: "VALID", nextCheckAt: due }));
    const service = new TaskApplicationService(
      tasks,
      audit,
      outbox,
      new BasicAuthorizationService(),
      { now: () => new Date("2026-07-24T08:00:00.000Z") },
      { next: () => "generated-id" },
    );

    const firstCount = await service.runEnforcementBatch(1);
    const quarantined = tasks.items.get("UNKNOWN");
    const count = await service.runEnforcementBatch(1);

    expect(firstCount).toBe(0);
    expect(count).toBe(1);
    expect(quarantined?.nextCheckAt.toISOString()).toBe("9999-12-31T00:00:00.000Z");
    expect(quarantined?.blockedReason).toMatch(/Automatikus levél letiltva/);
    expect(outbox.messages).toHaveLength(1);
    expect(outbox.messages[0]?.taskId).toBe("VALID");
    expect(audit.events.some((event) => event.eventType === "ENFORCEMENT_NOTIFICATION_BLOCKED")).toBe(true);
  });
});
