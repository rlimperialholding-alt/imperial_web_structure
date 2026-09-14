import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { IntegrationControlRoomService } from "../integration-control-room/service.js";

const connectorEventSchema = z.object({
  connectorId: z.string().min(1),
  kind: z.string().min(1),
  errorCode: z.string().optional(),
  errorMessage: z.string().min(1).optional(),
  reauthRequired: z.boolean().optional(),
  rateLimitedUntil: z.coerce.date().optional(),
});

export function registerIntegrationControlRoomRoutes(
  app: FastifyInstance,
  service: IntegrationControlRoomService,
): void {
  app.get("/v1/integration-control-room/dashboard", async (request) => {
    const actor = request.verifiedActor;
    if (!actor) throw new Error("Verified actor is required");
    return service.dashboard(actor.organizationId);
  });

  app.post("/v1/integration-control-room/connectors/success", async (request) => {
    const actor = request.verifiedActor;
    if (!actor) throw new Error("Verified actor is required");
    const body = connectorEventSchema.parse(request.body);
    return service.recordConnectorSuccess({
      organizationId: actor.organizationId,
      connectorId: body.connectorId,
      kind: body.kind,
    });
  });

  app.post("/v1/integration-control-room/connectors/failure", async (request) => {
    const actor = request.verifiedActor;
    if (!actor) throw new Error("Verified actor is required");
    const body = connectorEventSchema
      .extend({ errorMessage: z.string().min(1) })
      .parse(request.body);
    return service.recordConnectorFailure({
      organizationId: actor.organizationId,
      ...body,
    });
  });

  app.post("/v1/integration-control-room/retries", async (request) => {
    const actor = request.verifiedActor;
    if (!actor) throw new Error("Verified actor is required");
    const body = z.object({
      connectorId: z.string().min(1),
      operation: z.string().min(1),
      payload: z.unknown(),
      maxAttempts: z.number().int().min(1).max(20).optional(),
    }).parse(request.body);
    return service.enqueueRetry({
      organizationId: actor.organizationId,
      ...body,
      payload: body.payload ?? null,
    });
  });

  app.post(
    "/v1/integration-control-room/incidents/:id/acknowledge",
    async (request) => {
      const actor = request.verifiedActor;
      if (!actor) throw new Error("Verified actor is required");
      const params = z.object({ id: z.string().uuid() }).parse(request.params);
      return service.acknowledgeIncident({
        incidentId: params.id,
        actorId: actor.actorId,
      });
    },
  );

  app.post(
    "/v1/integration-control-room/incidents/:id/resolve",
    async (request) => {
      const actor = request.verifiedActor;
      if (!actor) throw new Error("Verified actor is required");
      const params = z.object({ id: z.string().uuid() }).parse(request.params);
      const body = z.object({ resolutionNote: z.string().min(3) }).parse(request.body);
      return service.resolveIncident({
        incidentId: params.id,
        actorId: actor.actorId,
        resolutionNote: body.resolutionNote,
      });
    },
  );

  app.post(
    "/v1/integration-control-room/dead-letters/:id/acknowledge",
    async (request) => {
      const actor = request.verifiedActor;
      if (!actor) throw new Error("Verified actor is required");
      const params = z.object({ id: z.string().uuid() }).parse(request.params);
      const body = z.object({ resolution: z.string().min(3) }).parse(request.body);
      return service.acknowledgeDeadLetter({
        deadLetterId: params.id,
        actorId: actor.actorId,
        resolution: body.resolution,
      });
    },
  );
}
