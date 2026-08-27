import type { FastifyInstance } from "fastify";

export async function registerRateLimit(
  app: FastifyInstance,
  input: { max: number; timeWindow: number },
): Promise<void> {
  await app.register(import("@fastify/rate-limit"), {
    max: input.max,
    timeWindow: input.timeWindow,
    keyGenerator: (request) => {
      const org = request.headers["x-organization-id"];
      const actor = request.headers["x-actor-id"];
      return `${typeof org === "string" ? org : "unknown"}:${
        typeof actor === "string" ? actor : request.ip
      }`;
    },
  });
}
