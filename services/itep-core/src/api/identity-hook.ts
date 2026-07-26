import type { FastifyInstance } from "fastify";
import type { IdentityVerifier } from "../security/identity-verifier.js";

declare module "fastify" {
  interface FastifyRequest {
    verifiedActor?: {
      actorId: string;
      organizationId: string;
      roles: string[];
      permissions: string[];
    };
  }
}

export function registerIdentityHook(
  app: FastifyInstance,
  verifier: IdentityVerifier,
): void {
  app.addHook("preHandler", async (request) => {
    if (
      request.url.startsWith("/health/") ||
      request.url.startsWith("/docs")
    ) {
      return;
    }

    const payload = request.headers["x-imperial-identity"];
    const signature = request.headers["x-imperial-identity-signature"];

    if (
      typeof payload !== "string" ||
      typeof signature !== "string"
    ) {
      throw new Error("Signed identity headers are required");
    }

    request.verifiedActor = verifier.verify(payload, signature);
  });
}
