import type { FastifyInstance } from "fastify";
import type { PrismaClient } from "@prisma/client";

export function registerHealthRoutes(
  app: FastifyInstance,
  prisma: PrismaClient,
): void {
  app.get("/health/live", async () => ({
    status: "ok",
    service: "imperial-itep-core",
    timestamp: new Date().toISOString(),
  }));

  app.get("/health/ready", async (_request, reply) => {
    try {
      await prisma.$queryRaw`SELECT 1`;
      return {
        status: "ready",
        database: "ok",
        timestamp: new Date().toISOString(),
      };
    } catch {
      return reply.code(503).send({
        status: "not_ready",
        database: "error",
        timestamp: new Date().toISOString(),
      });
    }
  });
}
