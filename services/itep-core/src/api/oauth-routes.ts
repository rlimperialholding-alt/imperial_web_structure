import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { ConnectorOAuthService } from "../connectors/oauth-service.js";
import { actorFromRequest } from "./actor-context.js";

const beginSchema = z.object({
  kind: z.enum(["GMAIL", "CALENDAR"]),
  redirectUri: z.string().url(),
  scopes: z.array(z.string().min(1)).min(1),
  loginHint: z.string().email().optional(),
});

const callbackSchema = z.object({
  state: z.string().min(1),
  code: z.string().min(1),
});

export function registerOAuthRoutes(
  app: FastifyInstance,
  service: ConnectorOAuthService,
): void {
  app.post("/v1/connectors/oauth/begin", async (request) => {
    const actor = actorFromRequest(request);
    const input = beginSchema.parse(request.body);
    return service.begin({
      organizationId: actor.organizationId,
      createdBy: actor.actorId,
      ...input,
    });
  });

  app.post("/v1/connectors/oauth/callback", async (request) => {
    actorFromRequest(request);
    return service.complete(callbackSchema.parse(request.body));
  });

  app.post<{ Params: { id: string } }>(
    "/v1/connectors/:id/disconnect",
    async (request) => {
      actorFromRequest(request);
      await service.disconnect(request.params.id);
      return { status: "DISCONNECTED" };
    },
  );
}
