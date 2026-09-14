import type { TaskPriority } from "./types.js";

export interface PriorityPolicy {
  openCheckIntervalDays: number;
  overdueCheckIntervalDays: number;
  escalationAfterDays?: number;
  incidentReportAfterDays?: number;
}

export const PRIORITY_POLICIES: Record<TaskPriority, PriorityPolicy> = {
  P1: {
    openCheckIntervalDays: 1,
    overdueCheckIntervalDays: 1,
    escalationAfterDays: 3,
    incidentReportAfterDays: 7,
  },
  P2: {
    openCheckIntervalDays: 2,
    overdueCheckIntervalDays: 1,
  },
  P3: {
    openCheckIntervalDays: 7,
    overdueCheckIntervalDays: 7,
  },
  P4: {
    openCheckIntervalDays: 30,
    overdueCheckIntervalDays: 30,
  },
};

const DAY_MS = 24 * 60 * 60 * 1000;

export function addDays(date: Date, days: number): Date {
  return new Date(date.getTime() + days * DAY_MS);
}

export function calculateNextCheck(
  priority: TaskPriority,
  now: Date,
  dueAt: Date,
): Date {
  const policy = PRIORITY_POLICIES[priority];
  const interval =
    now.getTime() > dueAt.getTime()
      ? policy.overdueCheckIntervalDays
      : policy.openCheckIntervalDays;

  return addDays(now, interval);
}

export function overdueDays(now: Date, dueAt: Date): number {
  if (now.getTime() <= dueAt.getTime()) return 0;
  return Math.floor((now.getTime() - dueAt.getTime()) / DAY_MS);
}

export type EscalationEvent =
  | "NONE"
  | "P1_ESCALATION"
  | "P1_INCIDENT_REPORT";

export function getEscalationEvent(
  priority: TaskPriority,
  now: Date,
  dueAt: Date,
): EscalationEvent {
  if (priority !== "P1") return "NONE";

  const days = overdueDays(now, dueAt);
  if (days >= 7) return "P1_INCIDENT_REPORT";
  if (days >= 3) return "P1_ESCALATION";
  return "NONE";
}
