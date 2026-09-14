import { DomainValidationError } from "../domain/errors.js";
import type { Task, TaskStatus } from "../domain/types.js";
import type {
  ActorContext,
  AuthorizationService,
} from "./ports.js";

const SENSITIVE_PERMISSIONS: Record<string, string> = {
  LEGAL: "task.sensitive.legal",
  FINANCIAL: "task.sensitive.financial",
  AUTHORITY: "task.sensitive.authority",
  HR: "task.sensitive.hr",
  CONFIDENTIAL: "task.sensitive.confidential",
};

export class BasicAuthorizationService implements AuthorizationService {
  assertCanCreateTask(actor: ActorContext, task: Task): void {
    this.assertSameOrganization(actor, task);
    this.assertSensitivity(actor, task);
    if (!actor.permissions.includes("task.create")) {
      throw new DomainValidationError("Missing task.create permission");
    }
  }

  assertCanReadTask(actor: ActorContext, task: Task): void {
    this.assertSameOrganization(actor, task);
    this.assertSensitivity(actor, task);

    const ownsTask =
      task.assigneeId === actor.actorId || task.issuerId === actor.actorId;
    const canReadAll = actor.permissions.includes("task.read.all");

    if (!ownsTask && !canReadAll) {
      throw new DomainValidationError("Task is outside actor scope");
    }
  }

  assertCanTransitionTask(
    actor: ActorContext,
    task: Task,
    target: TaskStatus,
  ): void {
    this.assertCanReadTask(actor, task);

    if (target === "CLOSED") {
      this.assertCanAcceptTask(actor, task);
      return;
    }

    const isParticipant =
      task.assigneeId === actor.actorId || task.issuerId === actor.actorId;
    if (!isParticipant && !actor.permissions.includes("task.transition.all")) {
      throw new DomainValidationError("Missing transition permission");
    }
  }

  assertCanAcceptTask(actor: ActorContext, task: Task): void {
    this.assertSameOrganization(actor, task);
    this.assertSensitivity(actor, task);
    const canAccept =
      actor.permissions.includes("task.accept") &&
      (task.issuerId === actor.actorId ||
        actor.permissions.includes("task.accept.all"));

    if (!canAccept) {
      throw new DomainValidationError("Missing task acceptance permission");
    }
  }

  private assertSameOrganization(actor: ActorContext, task: Task): void {
    if (actor.organizationId !== task.organizationId) {
      throw new DomainValidationError("Cross-organization access denied");
    }
  }

  private assertSensitivity(actor: ActorContext, task: Task): void {
    const permission = SENSITIVE_PERMISSIONS[task.sensitivity];
    if (permission && !actor.permissions.includes(permission)) {
      throw new DomainValidationError(
        `Missing sensitivity permission: ${permission}`,
      );
    }
  }
}
