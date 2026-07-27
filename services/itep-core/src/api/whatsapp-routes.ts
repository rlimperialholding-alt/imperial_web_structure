import type { FastifyInstance, FastifyRequest } from "fastify";
import { z } from "zod";
import type {
  WhatsAppService,
  WhatsAppWebhookPayload,
} from "../whatsapp/service.js";
import { actorFromRequest } from "./actor-context.js";

declare module "fastify" {
  interface FastifyRequest {
    rawBody?: string;
  }
}

const queryLimitSchema = z.object({
  limit: z.coerce.number().int().min(1).max(200).default(50),
});
const sendSchema = z.object({
  body: z.string().trim().min(1).max(4096),
  replyToProviderId: z.string().min(1).max(300).optional(),
});
const rejectSchema = z.object({
  reason: z.string().trim().min(3).max(1000),
});
const linkSchema = z.object({
  crmCustomerId: z.string().min(1).max(200).nullable().optional(),
  projectId: z.string().min(1).max(200).nullable().optional(),
  assignedUserId: z.string().min(1).max(200).nullable().optional(),
});

export function registerWhatsAppRoutes(
  app: FastifyInstance,
  service: WhatsAppService,
): void {
  app.get("/v1/webhooks/whatsapp", async (request, reply) => {
    const query = request.query as Record<string, unknown>;
    const mode = String(query["hub.mode"] ?? "");
    if (mode !== "subscribe") {
      return reply.code(400).send({ error: "INVALID_WEBHOOK_MODE" });
    }
    const challenge = service.verifyChallenge(
      String(query["hub.verify_token"] ?? ""),
      String(query["hub.challenge"] ?? ""),
    );
    return reply.type("text/plain").send(challenge);
  });

  app.post("/v1/webhooks/whatsapp", async (request, reply) => {
    const signature = request.headers["x-hub-signature-256"];
    if (typeof signature !== "string") {
      throw new Error("WhatsApp webhook signature is required");
    }
    const rawBody =
      request.rawBody ?? JSON.stringify(request.body ?? {});
    service.verifySignature(rawBody, signature);
    const result = await service.processWebhook(
      rawBody,
      request.body as WhatsAppWebhookPayload,
    );
    return reply.code(200).send(result);
  });

  app.get("/v1/whatsapp/conversations", async (request) => {
    const { limit } = queryLimitSchema.parse(request.query);
    return service.listConversations(actorFromRequest(request), limit);
  });

  app.get<{ Params: { id: string } }>(
    "/v1/whatsapp/conversations/:id/messages",
    async (request) => {
      const { limit } = queryLimitSchema.parse(request.query);
      return service.listMessages(
        actorFromRequest(request),
        request.params.id,
        limit,
      );
    },
  );

  app.patch<{ Params: { id: string } }>(
    "/v1/whatsapp/conversations/:id",
    async (request) =>
      service.linkConversation(
        actorFromRequest(request),
        request.params.id,
        linkSchema.parse(request.body),
      ),
  );

  app.post<{ Params: { id: string } }>(
    "/v1/whatsapp/conversations/:id/messages",
    async (request, reply) =>
      reply.code(201).send(
        await service.requestMessage(
          actorFromRequest(request),
          request.params.id,
          sendSchema.parse(request.body),
        ),
      ),
  );

  app.post<{ Params: { id: string } }>(
    "/v1/whatsapp/messages/:id/approve",
    async (request) =>
      service.approveMessage(actorFromRequest(request), request.params.id),
  );

  app.post<{ Params: { id: string } }>(
    "/v1/whatsapp/messages/:id/reject",
    async (request) => {
      const { reason } = rejectSchema.parse(request.body);
      return service.rejectMessage(
        actorFromRequest(request),
        request.params.id,
        reason,
      );
    },
  );
}

export function installRawJsonBodyCapture(app: FastifyInstance): void {
  app.removeContentTypeParser("application/json");
  app.addContentTypeParser(
    "application/json",
    { parseAs: "buffer" },
    (request: FastifyRequest, body: Buffer, done) => {
      const raw = body.toString("utf8");
      request.rawBody = raw;
      try {
        done(null, raw ? JSON.parse(raw) : {});
      } catch (error) {
        done(error as Error);
      }
    },
  );
}
