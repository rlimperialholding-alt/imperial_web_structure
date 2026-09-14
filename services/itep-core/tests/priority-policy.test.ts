import { describe, expect, it } from "vitest";
import {
  calculateNextCheck,
  getEscalationEvent,
  overdueDays,
} from "../src/domain/index.js";

describe("priority enforcement policy", () => {
  const due = new Date("2026-07-20T08:00:00.000Z");

  it("checks open P2 tasks every two days", () => {
    const now = new Date("2026-07-19T08:00:00.000Z");
    expect(calculateNextCheck("P2", now, due)).toEqual(
      new Date("2026-07-21T08:00:00.000Z"),
    );
  });

  it("checks overdue P2 tasks every day", () => {
    const now = new Date("2026-07-21T08:00:00.000Z");
    expect(calculateNextCheck("P2", now, due)).toEqual(
      new Date("2026-07-22T08:00:00.000Z"),
    );
  });

  it("escalates P1 after three overdue days", () => {
    expect(
      getEscalationEvent(
        "P1",
        new Date("2026-07-23T08:00:00.000Z"),
        due,
      ),
    ).toBe("P1_ESCALATION");
  });

  it("creates a P1 incident report after seven overdue days", () => {
    expect(
      getEscalationEvent(
        "P1",
        new Date("2026-07-27T08:00:00.000Z"),
        due,
      ),
    ).toBe("P1_INCIDENT_REPORT");
  });

  it("does not escalate non-P1 priorities", () => {
    expect(
      getEscalationEvent(
        "P2",
        new Date("2026-08-01T08:00:00.000Z"),
        due,
      ),
    ).toBe("NONE");
  });

  it("calculates whole overdue days", () => {
    expect(
      overdueDays(
        new Date("2026-07-23T07:59:59.000Z"),
        due,
      ),
    ).toBe(2);
  });
});
