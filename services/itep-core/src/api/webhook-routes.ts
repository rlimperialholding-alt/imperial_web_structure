import type { FastifyInstance } from "fastify";
import type { ConnectorWebhookService } from "../connectors/webhook-service.js";

export function registerWebhookRoutes(
  app: FastifyInstance,
  service: ConnectorWebhookService,
): void {
  app.post("/v1/webhooks/google/:channelId", async (request) => {
    const signature = request.headers["x-imperial-signature"];
    if (typeof signature !== "string") {
      throw new Error("Missing webhook signature");
    }

    const rawBody =
      typeof request.body === "string"
        ? request.body
        : JSON.stringify(request.body ?? {});

    return service.receive({
      externalChannelId: (request.params as any).channelId,
      rawBody,
      signature,
    });
  });
}
