import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { HumanAnneIncidentService } from "../human-anne/incident-service.js";
import { actorFromRequest } from "./actor-context.js";

const querySchema = z.object({
  severity: z.enum(["LOW", "MEDIUM", "HIGH", "CRITICAL"]).optional(),
  limit: z.coerce.number().int().positive().max(500).default(100),
});

const resolutionSchema = z.object({
  resolution: z.string().min(1),
});

export function registerHumanAnneRoutes(
  app: FastifyInstance,
  service: HumanAnneIncidentService,
): void {
  app.get("/v1/human-anne/incidents", async (request) => {
    actorFromRequest(request);
    const query = querySchema.parse(request.query);
    const incidents = await service.listOpen(query.severity, query.limit);
    return incidents.map(serializeIncident);
  });

  app.post<{ Params: { id: string } }>(
    "/v1/human-anne/incidents/:id/acknowledge",
    async (request) => {
      const actor = actorFromRequest(request);
      const incident = await service.acknowledge(
        request.params.id,
        actor.actorId,
      );
      return serializeIncident(incident);
    },
  );

  app.post<{ Params: { id: string } }>(
    "/v1/human-anne/incidents/:id/resolve",
    async (request) => {
      const actor = actorFromRequest(request);
      const { resolution } = resolutionSchema.parse(request.body);
      const incident = await service.resolve(
        request.params.id,
        actor.actorId,
        resolution,
      );
      return serializeIncident(incident);
    },
  );
}

function serializeIncident(incident: any) {
  return {
    ...incident,
    createdAt: incident.createdAt.toISOString(),
    acknowledgedAt: incident.acknowledgedAt?.toISOString(),
    resolvedAt: incident.resolvedAt?.toISOString(),
  };
}
