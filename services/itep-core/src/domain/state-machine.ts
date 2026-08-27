import { InvalidTransitionError, DomainValidationError } from "./errors.js";
import type { EvidenceSubmission, Task, TaskStatus } from "./types.js";

const TRANSITIONS: Record<TaskStatus, readonly TaskStatus[]> = {
  DRAFT: ["ASSIGNED", "CANCELLED"],
  ASSIGNED: ["AWAITING_ACKNOWLEDGEMENT", "IN_PROGRESS", "CANCELLED"],
  AWAITING_ACKNOWLEDGEMENT: ["IN_PROGRESS", "BLOCKED", "CANCELLED"],
  IN_PROGRESS: ["WAITING_EXTERNAL", "BLOCKED", "SUBMITTED", "CANCELLED"],
  WAITING_EXTERNAL: ["IN_PROGRESS", "BLOCKED", "SUBMITTED", "CANCELLED"],
  BLOCKED: ["IN_PROGRESS", "WAITING_EXTERNAL", "CANCELLED"],
  SUBMITTED: ["UNDER_REVIEW", "CHANGES_REQUESTED"],
  UNDER_REVIEW: ["CLOSED", "CHANGES_REQUESTED"],
  CHANGES_REQUESTED: ["IN_PROGRESS", "SUBMITTED", "CANCELLED"],
  CLOSED: [],
  CANCELLED: [],
};

export function canTransition(from: TaskStatus, to: TaskStatus): boolean {
  return TRANSITIONS[from].includes(to);
}

export function transitionTask(
  task: Task,
  target: TaskStatus,
  actorId: string,
  now: Date,
): Task {
  if (!canTransition(task.status, target)) {
    throw new InvalidTransitionError(task.status, target);
  }

  if (target === "SUBMITTED" && task.evidenceSubmissions.length === 0) {
    throw new DomainValidationError(
      "Task cannot be submitted without evidence",
    );
  }

  if (target === "CLOSED") {
    if (task.status !== "UNDER_REVIEW") {
      throw new InvalidTransitionError(task.status, target);
    }
    if (task.evidenceSubmissions.length === 0) {
      throw new DomainValidationError(
        "Task cannot be closed without evidence",
      );
    }

    return {
      ...task,
      status: target,
      acceptedBy: actorId,
      acceptedAt: now,
      rejectionReason: undefined,
    };
  }

  return {
    ...task,
    status: target,
    ...(target !== "CHANGES_REQUESTED"
      ? { rejectionReason: undefined }
      : {}),
  };
}

export function submitEvidence(
  task: Task,
  evidence: EvidenceSubmission,
): Task {
  if (
    task.status === "CLOSED" ||
    task.status === "CANCELLED"
  ) {
    throw new DomainValidationError(
      "Evidence cannot be submitted for closed or cancelled tasks",
    );
  }

  return {
    ...task,
    evidenceSubmissions: [...task.evidenceSubmissions, evidence],
  };
}

export function requestChanges(task: Task, reason: string): Task {
  if (!reason.trim()) {
    throw new DomainValidationError("Rejection reason is required");
  }
  if (!canTransition(task.status, "CHANGES_REQUESTED")) {
    throw new InvalidTransitionError(task.status, "CHANGES_REQUESTED");
  }

  return {
    ...task,
    status: "CHANGES_REQUESTED",
    rejectionReason: reason,
  };
}
