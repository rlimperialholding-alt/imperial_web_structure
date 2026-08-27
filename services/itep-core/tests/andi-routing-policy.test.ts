import { describe, expect, it } from "vitest";
import {
  resolveCandidateRouting,
  SYSTEM_BUSINESS_REVIEW_QUEUE,
  SYSTEM_TECHNICAL_QUEUE,
} from "../src/ingestion/task-candidate-adapter.js";
import type { TaskCandidate } from "../src/ingestion/types.js";

function candidate(overrides: Partial<TaskCandidate> = {}): TaskCandidate {
  return {
    sourceEventId: "source-1",
    organizationId: "imperial-holding",
    source: "GMAIL",
    sourceExternalId: "mail-1",
    title: "Partneri feladat",
    description: "Dolgozd fel a partner kérését: https://crm.example/work/42",
    issuerId: "digital-anne",
    assigneeId: "human-anne",
    priority: "P2",
    acceptanceCriteria: "A partneri kérés dokumentáltan lezárva.",
    evidenceDescription: "CRM readback és partneri visszaigazolás.",
    confidence: 99,
    requiresHumanReview: false,
    reasons: ["explicit_business_request"],
    sensitivity: "INTERNAL",
    ...overrides,
  };
}

describe("fail-closed candidate routing", () => {
  for (const title of [
    "Publication exception az adapterben",
    "Gmail OAuth hiba",
    "Meta API timeout",
  ]) {
    it(`routes ${title} to the unassigned technical queue`, () => {
      expect(resolveCandidateRouting(candidate({ title }))).toEqual({
        assigneeId: SYSTEM_TECHNICAL_QUEUE,
        status: "DRAFT",
        reason: "technical_incident_unassigned",
      });
    });
  }

  it("assigns a complete partner business task to Human Anne", () => {
    expect(resolveCandidateRouting(candidate({ title: "Napi partner-feladat" }))).toEqual({
      assigneeId: "human-anne",
      status: "ASSIGNED",
      reason: "complete_business_task",
    });
  });

  it("keeps incomplete business work in review", () => {
    expect(
      resolveCandidateRouting(
        candidate({ description: "Hívd vissza", acceptanceCriteria: "kész" }),
      ),
    ).toEqual({
      assigneeId: SYSTEM_BUSINESS_REVIEW_QUEUE,
      status: "DRAFT",
      reason: "business_task_requires_review",
    });
  });
});
