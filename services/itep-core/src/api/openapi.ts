import type { FastifyInstance } from "fastify";

export async function registerOpenApi(app: FastifyInstance): Promise<void> {
  await app.register(import("@fastify/swagger"), {
    openapi: {
      info: {
        title: "Imperial Intelligence – ITEP API",
        description:
          "Task Enforcement, Digital Anne, Human Anne and connector runtime API.",
        version: "1.0.0",
      },
      tags: [
        { name: "tasks" },
        { name: "reporting" },
        { name: "connectors" },
        { name: "human-anne" },
        { name: "ingestion" },
      ],
    },
  });

  await app.register(import("@fastify/swagger-ui"), {
    routePrefix: "/docs",
  });
}
