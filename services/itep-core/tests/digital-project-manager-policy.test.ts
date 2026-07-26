import { describe, expect, it } from "vitest";
import { evaluateDigitalActionRisk } from "../src/digital-project-managers/policy.js";

describe("digital project manager risk policy", () => {
  it.each(["R0", "R1", "R2", "R3"] as const)(
    "allows audited preparation for %s",
    (risk) => {
      expect(evaluateDigitalActionRisk(risk)).toMatchObject({
        decision: "AUTOMATION_ALLOWED",
        executionAllowed: true,
        humanApprovalRequired: false,
      });
    },
  );

  it.each(["R4", "R5"] as const)(
    "requires a human decision for %s",
    (risk) => {
      expect(evaluateDigitalActionRisk(risk)).toMatchObject({
        decision: "HUMAN_REVIEW_REQUIRED",
        executionAllowed: false,
        humanApprovalRequired: true,
      });
    },
  );

  it.each(["R6", "R7"] as const)(
    "blocks and escalates contractual or financial action %s",
    (risk) => {
      expect(evaluateDigitalActionRisk(risk)).toMatchObject({
        decision: "BLOCKED_AND_ESCALATED",
        executionAllowed: false,
        humanApprovalRequired: true,
      });
    },
  );
});

