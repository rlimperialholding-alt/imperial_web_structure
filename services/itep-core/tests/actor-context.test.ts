import { describe, expect, it } from "vitest";
import type { FastifyRequest } from "fastify";
import { actorFromRequest } from "../src/api/actor-context.js";

describe("actorFromRequest", () => {
  it("uses the actor already verified by the signed identity hook", () => {
    const verifiedActor = {
      actorId: "github-actions",
      organizationId: "imperial-holding",
      roles: ["SYSTEM"],
      permissions: ["task.read.all"],
    };
    const request = {
      headers: {},
      verifiedActor,
    } as unknown as FastifyRequest;

    expect(actorFromRequest(request)).toEqual(verifiedActor);
  });

  it("retains the legacy header fallback for internal callers", () => {
    const request = {
      headers: {
        "x-actor-id": "legacy-worker",
        "x-organization-id": "imperial-holding",
        "x-roles": "SYSTEM",
        "x-permissions": "task.read.all, task.create",
      },
    } as unknown as FastifyRequest;

    expect(actorFromRequest(request)).toEqual({
      actorId: "legacy-worker",
      organizationId: "imperial-holding",
      roles: ["SYSTEM"],
      permissions: ["task.read.all", "task.create"],
    });
  });
});
