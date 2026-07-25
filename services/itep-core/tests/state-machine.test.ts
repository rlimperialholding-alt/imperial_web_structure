import { describe, expect, it } from "vitest";
import {
  DomainValidationError,
  InvalidTransitionError,
  requestChanges,
  submitEvidence,
  transitionTask,
} from "../src/domain/index.js";
import { makeTask } from "./fixtures.js";

describe("ITEP task state machine", () => {
  it("prevents submitting without evidence", () => {
    expect(() =>
      transitionTask(
        makeTask(),
        "SUBMITTED",
        "employee-1",
        new Date("2026-07-27T08:00:00.000Z"),
      ),
    ).toThrow(DomainValidationError);
  });

  it("requires review before closure", () => {
    const task = submitEvidence(makeTask(), {
      id: "evidence-1",
      type: "DOCUMENT",
      uri: "gdrive://document-1",
      submittedAt: new Date("2026-07-27T08:00:00.000Z"),
      submittedBy: "employee-1",
    });

    expect(() =>
      transitionTask(
        task,
        "CLOSED",
        "manager-1",
        new Date("2026-07-27T09:00:00.000Z"),
      ),
    ).toThrow(InvalidTransitionError);
  });

  it("closes only an evidenced task under review", () => {
    let task = submitEvidence(makeTask(), {
      id: "evidence-1",
      type: "DOCUMENT",
      uri: "gdrive://document-1",
      submittedAt: new Date("2026-07-27T08:00:00.000Z"),
      submittedBy: "employee-1",
    });
    task = transitionTask(
      task,
      "SUBMITTED",
      "employee-1",
      new Date("2026-07-27T08:01:00.000Z"),
    );
    task = transitionTask(
      task,
      "UNDER_REVIEW",
      "manager-1",
      new Date("2026-07-27T08:02:00.000Z"),
    );
    task = transitionTask(
      task,
      "CLOSED",
      "manager-1",
      new Date("2026-07-27T08:03:00.000Z"),
    );

    expect(task.status).toBe("CLOSED");
    expect(task.acceptedBy).toBe("manager-1");
    expect(task.acceptedAt).toEqual(
      new Date("2026-07-27T08:03:00.000Z"),
    );
  });

  it("requires a reason when changes are requested", () => {
    const submitted = makeTask({
      status: "SUBMITTED",
      evidenceSubmissions: [
        {
          id: "evidence-1",
          type: "DOCUMENT",
          uri: "gdrive://document-1",
          submittedAt: new Date("2026-07-27T08:00:00.000Z"),
          submittedBy: "employee-1",
        },
      ],
    });

    expect(() => requestChanges(submitted, " ")).toThrow(
      DomainValidationError,
    );
  });
});
