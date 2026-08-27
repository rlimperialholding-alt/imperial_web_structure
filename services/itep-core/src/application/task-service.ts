import {
  calculateNextCheck,
  createAuditEvent,
  getEscalationEvent,
  submitEvidence,
  transitionTask,
  validateTask,
} from "../domain/index.js";
import { renderTaskReminder } from "../notifications/templates.js";
import { buildSemanticTaskFingerprint } from "../ingestion/fingerprint.js";
import type {
  EvidenceSubmission,
  Task,
  TaskStatus,
} from "../domain/types.js";
import type {
  ActorContext,
  AuditRepository,
  AuthorizationService,
  Clock,
  IdGenerator,
  NotificationOutbox,
  TaskRepository,
} from "./ports.js";

export interface CreateTaskInput extends Omit<
  Task,
  "id" | "createdAt" | "lastCheckedAt" | "nextCheckAt" |
  "reminderLevel" | "evidenceSubmissions" | "status"
> {
  status?: Extract<TaskStatus, "DRAFT" | "ASSIGNED">;
}

export class TaskApplicationService {
  constructor(
    private readonly tasks: TaskRepository,
    private readonly audit: AuditRepository,
    private readonly outbox: NotificationOutbox,
    private readonly auth: AuthorizationService,
    private readonly clock: Clock,
    private readonly ids: IdGenerator,
  ) {}

  async create(actor: ActorContext, input: CreateTaskInput): Promise<Task> {
    const now = this.clock.now();
    const task: Task = {
      ...input,
      id: this.ids.next(),
      createdAt: now,
      semanticFingerprint: buildSemanticTaskFingerprint({ organizationId: input.organizationId, title: input.title, assigneeId: input.assigneeId, dueAt: input.dueAt }),
      status: input.status ?? "ASSIGNED",
      evidenceSubmissions: [],
      nextCheckAt: calculateNextCheck(input.priority, now, input.dueAt),
      reminderLevel: 0,
    };

    this.auth.assertCanCreateTask(actor, task);
    validateTask(task);
    await this.tasks.create(task);
    await this.audit.append(
      createAuditEvent(task, "TASK_CREATED", actor.actorId, now, {
        priority: task.priority,
        dueAt: task.dueAt.toISOString(),
        assigneeId: task.assigneeId,
      }),
    );

    return task;
  }

  async transition(
    actor: ActorContext,
    taskId: string,
    target: TaskStatus,
  ): Promise<Task> {
    const task = await this.requireTask(taskId);
    this.auth.assertCanTransitionTask(actor, task, target);

    if (target === "IN_PROGRESS" && await this.tasks.hasOpenDependencies(taskId)) {
      throw new Error("Task has open dependencies");
    }

    const now = this.clock.now();
    const changed = transitionTask(task, target, actor.actorId, now);
    await this.tasks.save(changed);
    await this.audit.append(
      createAuditEvent(changed, "TASK_STATUS_CHANGED", actor.actorId, now, {
        from: task.status,
        to: target,
      }),
    );
    return changed;
  }

  async addEvidence(
    actor: ActorContext,
    taskId: string,
    evidence: Omit<EvidenceSubmission, "id" | "submittedAt" | "submittedBy">,
  ): Promise<Task> {
    const task = await this.requireTask(taskId);
    this.auth.assertCanTransitionTask(actor, task, task.status);

    const now = this.clock.now();
    const submission: EvidenceSubmission = {
      ...evidence,
      id: this.ids.next(),
      submittedAt: now,
      submittedBy: actor.actorId,
    };
    const changed = submitEvidence(task, submission);

    await this.tasks.save(changed);
    await this.audit.append(
      createAuditEvent(changed, "EVIDENCE_SUBMITTED", actor.actorId, now, {
        evidenceId: submission.id,
        type: submission.type,
        uri: submission.uri,
      }),
    );
    return changed;
  }

  async runEnforcementBatch(limit = 100): Promise<number> {
    const now = this.clock.now();
    const dueTasks = await this.tasks.findDueForCheck(now, limit);

    for (const task of dueTasks) {
      const overdue = now.getTime() > task.dueAt.getTime();
      const escalation = getEscalationEvent(task.priority, now, task.dueAt);
      const reminderLevel = task.reminderLevel + 1;

      const cc =
        escalation === "NONE"
          ? []
          : [task.escalationPersonId];

      const rendered = renderTaskReminder(
        task,
        reminderLevel,
        escalation,
      );

      await this.outbox.enqueue({
        taskId: task.id,
        eventKey: escalation,
        channel: "EMAIL",
        recipient: task.contact.email,
        cc,
        subject: rendered.subject,
        body: rendered.text,
        scheduledFor: now,
        idempotencyKey:
          `${task.id}:${task.nextCheckAt.toISOString()}:${reminderLevel}:${escalation}`,
      });

      const changed: Task = {
        ...task,
        reminderLevel,
        lastCheckedAt: now,
        nextCheckAt: calculateNextCheck(task.priority, now, task.dueAt),
      };
      await this.tasks.save(changed);
      await this.audit.append(
        createAuditEvent(changed, "ENFORCEMENT_CHECKED", "digital-anne", now, {
          reminderLevel,
          escalation,
          nextCheckAt: changed.nextCheckAt.toISOString(),
        }),
      );
    }

    return dueTasks.length;
  }

  private async requireTask(id: string): Promise<Task> {
    const task = await this.tasks.getById(id);
    if (!task) throw new Error(`Task not found: ${id}`);
    return task;
  }
}
