import { describe, expect, it } from "vitest";
import {
  buildWorkflowTasks,
  explainDailyPriority,
  type EnterpriseDomainEvent,
} from "../src/orchestration/workflow-engine.js";

const defaults = {
  issuerId: "smart-calendar",
  escalationPersonId: "director",
  contactEmail: "test@imperial.local",
};

function event(
  eventType: EnterpriseDomainEvent["eventType"],
): EnterpriseDomainEvent {
  return {
    organizationId: "imperial-holding",
    source: "test",
    externalEventId: `external-${eventType}`,
    eventType,
    projectId: "PRJ-001",
    ownerId: "digital-kalman",
    occurredAt: new Date("2026-07-26T08:00:00Z"),
    payload: {},
  };
}

describe("smart calendar enterprise workflows", () => {
  it("creates project start and document checks from a signed contract", () => {
    const tasks = buildWorkflowTasks(
      event("CONTRACT_SIGNED"),
      defaults,
      new Date("2026-07-26T08:00:00Z"),
    );
    expect(tasks).toHaveLength(2);
    expect(tasks.map((task) => task.sourceExternalId)).toEqual([
      "external-CONTRACT_SIGNED:project-start",
      "external-CONTRACT_SIGNED:document-check",
    ]);
    expect(tasks.every((task) => task.relatedEntityIds.includes("PRJ-001"))).toBe(true);
  });

  it("creates a P1 financial approval task for payment due", () => {
    const [task] = buildWorkflowTasks(event("PAYMENT_DUE"), defaults);
    expect(task).toMatchObject({
      priority: "P1",
      sensitivity: "FINANCIAL",
      evidenceRequirement: { type: "APPROVAL" },
    });
  });

  it("creates a P1 cross-module task for approved changes", () => {
    const [task] = buildWorkflowTasks(event("CHANGE_APPROVED"), defaults);
    expect(task.title).toContain("változás");
    expect(task.acceptanceCriteria).toContain("változásazonosító");
  });

  it("creates an evidence-bound stop point for failed quality checks", () => {
    const [task] = buildWorkflowTasks(event("QUALITY_CHECK_FAILED"), defaults);
    expect(task).toMatchObject({
      priority: "P1",
      evidenceRequirement: { type: "PHOTO", machineVerifiable: false },
    });
    expect(task.title).toContain("STOP");
  });

  it("ranks overdue and blocked work explainably", () => {
    const result = explainDailyPriority({
      priority: "P1",
      dueAt: new Date("2026-07-25T08:00:00Z"),
      reminderLevel: 2,
      status: "BLOCKED",
    }, new Date("2026-07-26T08:00:00Z"));
    expect(result.score).toBeGreaterThan(400);
    expect(result.reasons.join(" ")).toMatch(/késés|Blokkolt/);
  });
});
