import type { AuditEvent, EvidenceSubmission, Task, TaskStatus } from "../domain/types.js";

export interface TaskRepository {
  getById(id: string): Promise<Task | null>;
  create(task: Task): Promise<void>;
  save(task: Task, expectedVersion?: number): Promise<void>;
  findDueForCheck(now: Date, limit: number): Promise<Task[]>;
  hasOpenDependencies(taskId: string): Promise<boolean>;
}

export interface AuditRepository {
  append(event: AuditEvent): Promise<void>;
}

export interface NotificationMessage {
  taskId: string;
  eventKey: string;
  channel: "EMAIL" | "IN_APP" | "SMS";
  recipient: string;
  cc: string[];
  subject: string;
  body: string;
  scheduledFor: Date;
  idempotencyKey: string;
}

export interface NotificationOutbox {
  enqueue(message: NotificationMessage): Promise<void>;
}

export interface EvidenceVerifier {
  verify(task: Task, evidence: EvidenceSubmission): Promise<{
    accepted: boolean;
    reason: string;
    verifiedBy: string;
  }>;
}

export interface Clock {
  now(): Date;
}

export interface IdGenerator {
  next(): string;
}

export interface ActorContext {
  actorId: string;
  organizationId: string;
  roles: string[];
  permissions: string[];
}

export interface AuthorizationService {
  assertCanCreateTask(actor: ActorContext, task: Task): void;
  assertCanReadTask(actor: ActorContext, task: Task): void;
  assertCanTransitionTask(
    actor: ActorContext,
    task: Task,
    target: TaskStatus,
  ): void;
  assertCanAcceptTask(actor: ActorContext, task: Task): void;
}
