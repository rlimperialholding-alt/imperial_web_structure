import type { FastifyInstance } from "fastify";
import type { ConnectorHealthService } from "../connectors/health-service.js";
import { actorFromRequest } from "./actor-context.js";

export function registerConnectorHealthRoutes(
  app: FastifyInstance,
  service: ConnectorHealthService,
): void {
  app.get("/v1/connectors/health", async (request) => {
    actorFromRequest(request);
    return service.inspect();
  });
}
