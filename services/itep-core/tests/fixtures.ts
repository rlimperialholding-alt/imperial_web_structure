import type { Task } from "../src/domain/types.js";
import { calculateNextCheck } from "../src/domain/priority-policy.js";

export function makeTask(overrides: Partial<Task> = {}): Task {
  const createdAt = new Date("2026-07-24T08:00:00.000Z");
  const dueAt = new Date("2026-07-28T08:00:00.000Z");

  return {
    id: "ITEP-TEST-001",
    organizationId: "imperial-holding",
    source: "MANUAL",
    issuerId: "director-1",
    assigneeId: "employee-1",
    assigneeType: "EMPLOYEE",
    title: "Kötelező dokumentum átadása",
    description: "A dokumentumot a megadott feltételek szerint át kell adni.",
    priority: "P1",
    createdAt,
    dueAt,
    acceptanceCriteria: "A jóváhagyott PDF elérhető a Drive-ban.",
    evidenceRequirement: {
      type: "DOCUMENT",
      description: "Jóváhagyott PDF",
      machineVerifiable: false,
    },
    evidenceSubmissions: [],
    escalationPersonId: "manager-1",
    contact: { email: "employee@example.com" },
    status: "IN_PROGRESS",
    nextCheckAt: calculateNextCheck("P1", createdAt, dueAt),
    reminderLevel: 0,
    relatedEntityIds: [],
    dependencies: [],
    sensitivity: "INTERNAL",
    ...overrides,
  };
}
