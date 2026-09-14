import { describe, expect, it } from "vitest";
import {
  DomainValidationError,
  validateTask,
} from "../src/domain/index.js";
import { makeTask } from "./fixtures.js";

describe("task validation", () => {
  it("accepts a valid task", () => {
    expect(() => validateTask(makeTask())).not.toThrow();
  });

  it("rejects missing acceptance criteria", () => {
    expect(() =>
      validateTask(makeTask({ acceptanceCriteria: " " })),
    ).toThrow(DomainValidationError);
  });

  it("rejects invalid email address", () => {
    expect(() =>
      validateTask(makeTask({ contact: { email: "invalid" } })),
    ).toThrow(DomainValidationError);
  });

  it("rejects closed task without acceptance metadata", () => {
    expect(() =>
      validateTask(
        makeTask({
          status: "CLOSED",
          evidenceSubmissions: [
            {
              id: "evidence-1",
              type: "DOCUMENT",
              uri: "gdrive://document-1",
              submittedAt: new Date("2026-07-27T08:00:00.000Z"),
              submittedBy: "employee-1",
            },
          ],
        }),
      ),
    ).toThrow(DomainValidationError);
  });
});
