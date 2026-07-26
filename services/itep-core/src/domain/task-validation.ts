import { DomainValidationError } from "./errors.js";
import type { Task } from "./types.js";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateTask(task: Task): void {
  const requiredTextFields: Array<[string, string]> = [
    ["id", task.id],
    ["organizationId", task.organizationId],
    ["source", task.source],
    ["issuerId", task.issuerId],
    ["assigneeId", task.assigneeId],
    ["title", task.title],
    ["description", task.description],
    ["acceptanceCriteria", task.acceptanceCriteria],
    ["escalationPersonId", task.escalationPersonId],
    ["evidenceRequirement.description", task.evidenceRequirement.description],
  ];

  for (const [field, value] of requiredTextFields) {
    if (!value.trim()) {
      throw new DomainValidationError(`${field} is required`);
    }
  }

  if (!EMAIL_PATTERN.test(task.contact.email)) {
    throw new DomainValidationError("A valid contact email is required");
  }

  if (task.dueAt.getTime() <= task.createdAt.getTime()) {
    throw new DomainValidationError("dueAt must be after createdAt");
  }

  if (task.priority === "P4" && !task.nextCheckAt) {
    throw new DomainValidationError("P4 tasks require a review date");
  }

  if (task.status === "CLOSED") {
    if (!task.acceptedBy || !task.acceptedAt) {
      throw new DomainValidationError(
        "Closed tasks require acceptedBy and acceptedAt",
      );
    }
    if (task.evidenceSubmissions.length === 0) {
      throw new DomainValidationError(
        "Closed tasks require at least one evidence submission",
      );
    }
  }
}
