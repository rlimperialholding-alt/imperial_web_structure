import { randomUUID } from "node:crypto";
import type { AuditEvent, Task } from "./types.js";

export function createAuditEvent(
  task: Task,
  eventType: string,
  actorId: string,
  occurredAt: Date,
  payload: Record<string, unknown> = {},
): AuditEvent {
  return Object.freeze({
    id: randomUUID(),
    taskId: task.id,
    eventType,
    actorId,
    occurredAt,
    payload: Object.freeze({ ...payload }),
  });
}
