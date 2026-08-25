import { describe, expect, it } from "vitest";
import type { TaskApplicationService } from "../src/application/task-service.js";
import type { ActorContext } from "../src/application/ports.js";
import { TaskApplicationCandidateCreator } from "../src/ingestion/task-candidate-adapter.js";
import type { TaskCandidate } from "../src/ingestion/types.js";
import { makeTask } from "./fixtures.js";

describe("TaskApplicationCandidateCreator", () => {
  it("never uses an external Gmail sender as an employee reminder address", async () => {
    const created: Array<{ contact: { email: string } }> = [];
    const service = {
      async create(_actor: ActorContext, input: { contact: { email: string } }) {
        created.push(input);
        return makeTask({ contact: input.contact });
      },
    } as unknown as TaskApplicationService;
    const actor: ActorContext = {
      actorId: "digital-anne",
      organizationId: "imperial-holding",
      roles: ["SYSTEM"],
      permissions: ["task.create"],
    };
    const candidate: TaskCandidate = {
      sourceEventId: "SRC-GMAIL-1",
      organizationId: "imperial-holding",
      source: "GMAIL",
      sourceExternalId: "gmail-1",
      issuerId: "digital-anne",
      title: "Külső kérés",
      description: "Külső feladó levele.",
      priority: "P2",
      dueAt: new Date("2026-08-27T08:00:00.000Z"),
      acceptanceCriteria: "A levelet át kell nézni.",
      evidenceDescription: "Belső válasz",
      contactEmail: "external@example.hu",
      confidence: 0.8,
      requiresHumanReview: true,
      reasons: [],
      sensitivity: "INTERNAL",
    };
    const creator = new TaskApplicationCandidateCreator(service, actor, {
      resolveAssignee: () => "employee-1",
      resolveEscalationPerson: () => "manager-1",
      resolveContactEmail: () => "employee@imperialholding.hu",
    });

    await creator.createFromCandidate(candidate);

    expect(created[0]?.contact.email).toBe("employee@imperialholding.hu");
  });
});
