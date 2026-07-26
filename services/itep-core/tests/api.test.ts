import { describe, expect, it } from "vitest";
import Fastify from "fastify";
import { ZodError } from "zod";
import { createTaskSchema } from "../src/api/schemas.js";

describe("API schemas", () => {
  it("rejects a task without acceptance criteria", () => {
    expect(() =>
      createTaskSchema.parse({
        organizationId: "imperial-holding",
        source: "MANUAL",
        issuerId: "director-1",
        assigneeId: "employee-1",
        assigneeType: "EMPLOYEE",
        title: "Teszt",
        description: "Teszt feladat",
        priority: "P1",
        dueAt: "2026-08-01T08:00:00Z",
        evidenceRequirement: {
          type: "DOCUMENT",
          description: "PDF",
          machineVerifiable: false,
        },
        escalationPersonId: "manager-1",
        contact: { email: "employee@example.com" },
        sensitivity: "INTERNAL",
      }),
    ).toThrow(ZodError);
  });

  it("accepts a valid task payload", () => {
    const result = createTaskSchema.parse({
      organizationId: "imperial-holding",
      source: "MANUAL",
      issuerId: "director-1",
      assigneeId: "employee-1",
      assigneeType: "EMPLOYEE",
      title: "Teszt",
      description: "Teszt feladat",
      priority: "P1",
      dueAt: "2026-08-01T08:00:00Z",
      acceptanceCriteria: "A PDF jóváhagyva.",
      evidenceRequirement: {
        type: "DOCUMENT",
        description: "PDF",
        machineVerifiable: false,
      },
      escalationPersonId: "manager-1",
      contact: { email: "employee@example.com" },
      sensitivity: "INTERNAL",
    });

    expect(result.priority).toBe("P1");
    expect(result.dueAt).toBeInstanceOf(Date);
  });
});
