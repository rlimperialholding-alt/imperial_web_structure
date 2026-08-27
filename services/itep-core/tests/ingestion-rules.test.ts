import { describe, expect, it } from "vitest";
import {
  IngestionRuleEngine,
  defaultIngestionRules,
} from "../src/ingestion/rules.js";
import { normalizeGmailEvent } from "../src/ingestion/normalizers.js";

describe("IngestionRuleEngine", () => {
  it("creates a P1 task candidate from a NAV mail", () => {
    const event = normalizeGmailEvent(
      {
        organizationId: "imperial",
        messageId: "m1",
        internalDate: new Date("2026-07-24T08:00:00Z"),
        from: "nav@example.hu",
        to: ["office@example.hu"],
        subject: "NAV határidő",
        bodyText: "Kérjük a dokumentumot sürgősen megküldeni.",
      },
      new Date(),
    );

    const result = new IngestionRuleEngine(
      defaultIngestionRules(),
    ).evaluate(event);

    expect(result.action).toBe("CREATE_TASK");
    expect(result.candidate?.priority).toBe("P1");
    expect(result.candidate?.sensitivity).toBe("AUTHORITY");
  });

  it("ignores unsubscribe noise", () => {
    const event = normalizeGmailEvent(
      {
        organizationId: "imperial",
        messageId: "m2",
        internalDate: new Date(),
        from: "newsletter@example.com",
        to: ["office@example.hu"],
        subject: "Hírlevél",
        bodyText: "Unsubscribe here.",
      },
      new Date(),
    );

    const result = new IngestionRuleEngine(
      defaultIngestionRules(),
    ).evaluate(event);
    expect(result.action).toBe("IGNORE");
  });
});
