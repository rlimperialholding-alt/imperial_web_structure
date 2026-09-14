import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import {
  normalizeCalendarEvent,
  normalizeGmailEvent,
} from "../ingestion/normalizers.js";
import { actorFromRequest } from "./actor-context.js";

const gmailSchema = z.object({
  messageId: z.string().min(1),
  threadId: z.string().optional(),
  internalDate: z.coerce.date(),
  from: z.string().email(),
  to: z.array(z.string().email()),
  cc: z.array(z.string().email()).optional(),
  subject: z.string().optional(),
  bodyText: z.string().optional(),
  labels: z.array(z.string()).optional(),
});

const calendarSchema = z.object({
  eventId: z.string().min(1),
  startAt: z.coerce.date(),
  endAt: z.coerce.date(),
  title: z.string().min(1),
  description: z.string().optional(),
  organizer: z.string().email(),
  attendees: z.array(z.string().email()),
  status: z.string().min(1),
});

export function registerIngestionRoutes(
  app: FastifyInstance,
  service: SourceIngestionService,
): void {
  app.post("/v1/ingestion/gmail", async (request, reply) => {
    const actor = actorFromRequest(request);
    const body = gmailSchema.parse(request.body);
    const event = normalizeGmailEvent(
      {
        organizationId: actor.organizationId,
        actorId: actor.actorId,
        ...body,
      },
      new Date(),
    );
    return reply.code(202).send(await service.ingest(event));
  });

  app.post("/v1/ingestion/calendar", async (request, reply) => {
    const actor = actorFromRequest(request);
    const body = calendarSchema.parse(request.body);
    const event = normalizeCalendarEvent(
      {
        organizationId: actor.organizationId,
        actorId: actor.actorId,
        ...body,
      },
      new Date(),
    );
    return reply.code(202).send(await service.ingest(event));
  });
}
