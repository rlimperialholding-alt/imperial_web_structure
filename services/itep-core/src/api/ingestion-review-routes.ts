import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { IngestionReviewService } from "../ingestion/review-service.js";
import { actorFromRequest } from "./actor-context.js";

const listSchema = z.object({
  limit: z.coerce.number().int().positive().max(500).default(100),
});
const approveSchema = z.object({
  title: z.string().min(1).optional(),
  assigneeId: z.string().min(1).optional(),
  escalationPersonId: z.string().min(1).optional(),
  contactEmail: z.string().email().optional(),
  dueAt: z.coerce.date().optional(),
  priority: z.enum(["P1", "P2", "P3", "P4"]).optional(),
});
const rejectSchema = z.object({
  reason: z.string().min(1),
});

export function registerIngestionReviewRoutes(
  app: FastifyInstance,
  service: IngestionReviewService,
): void {
  app.get("/v1/ingestion/review", async (request) => {
    const actor = actorFromRequest(request);
    const { limit } = listSchema.parse(request.query);
    return service.listOpen(actor.organizationId, limit);
  });

  app.post<{ Params: { id: string } }>(
    "/v1/ingestion/review/:id/approve",
    async (request) => {
      const actor = actorFromRequest(request);
      const overrides = approveSchema.parse(request.body);
      return service.approve(request.params.id, actor.actorId, overrides);
    },
  );

  app.post<{ Params: { id: string } }>(
    "/v1/ingestion/review/:id/reject",
    async (request) => {
      const actor = actorFromRequest(request);
      const { reason } = rejectSchema.parse(request.body);
      await service.reject(request.params.id, actor.actorId, reason);
      return { status: "REJECTED" };
    },
  );
}
