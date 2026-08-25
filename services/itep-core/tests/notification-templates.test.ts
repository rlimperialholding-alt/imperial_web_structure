import { describe, expect, it } from "vitest";
import { renderTaskReminder } from "../src/notifications/templates.js";
import { makeTask } from "./fixtures.js";

describe("notification templates", () => {
  it("renders critical escalation content", () => {
    const result = renderTaskReminder(
      makeTask(),
      4,
      "P1_ESCALATION",
    );

    expect(result.subject).toContain("Sürgős feladat");
    expect(result.text).toContain("Teendő");
    expect(result.html).toContain("<strong>Határidő:</strong>");
    expect(result.audience).toBe("external");
  });

  it("escapes user-controlled HTML", () => {
    const result = renderTaskReminder(
      makeTask({ title: "<script>alert(1)</script>" }),
      1,
      "NONE",
    );
    expect(result.html).not.toContain("<script>");
    expect(result.html).toContain("&lt;script&gt;");
  });

  it("supports the legacy Imperial organization alias", () => {
    const result = renderTaskReminder(
      makeTask({ organizationId: "imperial" }),
      1,
      "NONE",
    );

    expect(result.text).toContain("Imperial Holding");
  });
});
