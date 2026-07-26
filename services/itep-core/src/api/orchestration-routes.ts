import type { FastifyInstance } from "fastify";
import type { Prisma, PrismaClient } from "@prisma/client";
import { z } from "zod";
import type { TaskApplicationService } from "../application/task-service.js";
import {
  buildWorkflowTasks,
  explainDailyPriority,
} from "../orchestration/workflow-engine.js";
import { actorFromRequest } from "./actor-context.js";

const eventSchema = z.object({
  organizationId: z.string().min(1),
  source: z.string().min(1),
  externalEventId: z.string().min(1),
  eventType: z.enum([
    "CONTRACT_SIGNED",
    "PAYMENT_DUE",
    "CHANGE_APPROVED",
    "QUALITY_CHECK_FAILED",
  ]),
  projectId: z.string().min(1),
  ownerId: z.string().min(1),
  occurredAt: z.coerce.date(),
  dueAt: z.coerce.date().optional(),
  title: z.string().min(1).optional(),
  payload: z.record(z.unknown()).default({}),
});

const dailyQuery = z.object({
  limit: z.coerce.number().int().min(1).max(200).default(100),
});

export function registerOrchestrationRoutes(
  app: FastifyInstance,
  prisma: PrismaClient,
  tasks: TaskApplicationService,
  defaults: {
    issuerId: string;
    escalationPersonId: string;
    contactEmail: string;
  },
) {
  app.post("/v1/orchestration/events", async (request, reply) => {
    const actor = actorFromRequest(request);
    const body = eventSchema.parse(request.body);
    if (body.organizationId !== actor.organizationId) {
      return reply.code(403).send({ error: "ORGANIZATION_SCOPE_MISMATCH" });
    }
    const unique = {
      organizationId_source_externalEventId: {
        organizationId: body.organizationId,
        source: body.source,
        externalEventId: body.externalEventId,
      },
    };
    const previous = await prisma.orchestrationEvent.findUnique({ where: unique });
    if (previous) {
      return {
        idempotent: true,
        eventId: previous.id,
        status: previous.status,
        taskIds: previous.taskIds,
      };
    }
    const event = await prisma.orchestrationEvent.create({
      data: {
        organizationId: body.organizationId,
        source: body.source,
        externalEventId: body.externalEventId,
        eventType: body.eventType,
        projectId: body.projectId,
        ownerId: body.ownerId,
        status: "RECEIVED",
        payload: body.payload as Prisma.InputJsonValue,
        taskIds: [],
        occurredAt: body.occurredAt,
      },
    });
    try {
      const taskIds: string[] = [];
      const workflowTasks = buildWorkflowTasks(body, defaults);
      for (const input of workflowTasks) {
        let task = await tasks.create(actor, input);
        if (body.eventType === "QUALITY_CHECK_FAILED") {
          task = await tasks.transition(actor, task.id, "BLOCKED");
        }
        taskIds.push(task.id);
      }
      await prisma.orchestrationEvent.update({
        where: { id: event.id },
        data: {
          status: "PROCESSED",
          taskIds,
          processedAt: new Date(),
        },
      });
      return reply.code(201).send({
        idempotent: false,
        eventId: event.id,
        status: "PROCESSED",
        taskIds,
      });
    } catch (error) {
      await prisma.orchestrationEvent.update({
        where: { id: event.id },
        data: {
          status: "FAILED",
          lastError: error instanceof Error ? error.message : String(error),
        },
      });
      throw error;
    }
  });

  app.get("/v1/orchestration/events/audit", async (request) => {
    const actor = actorFromRequest(request);
    return {
      events: await prisma.orchestrationEvent.findMany({
        where: { organizationId: actor.organizationId },
        orderBy: { receivedAt: "desc" },
        take: 200,
      }),
    };
  });

  app.get<{ Params: { ownerId: string } }>(
    "/v1/daily/:ownerId/prioritized",
    async (request, reply) => {
      const actor = actorFromRequest(request);
      if (
        request.params.ownerId !== actor.actorId &&
        !actor.permissions.includes("task.read.all") &&
        !actor.roles.includes("SYSTEM")
      ) {
        return reply.code(403).send({ error: "TASK_READ_FORBIDDEN" });
      }
      const { limit } = dailyQuery.parse(request.query);
      const now = new Date();
      const rows = await prisma.itepTask.findMany({
        where: {
          organizationId: actor.organizationId,
          assigneeId: request.params.ownerId,
          status: { notIn: ["CLOSED", "CANCELLED"] },
        },
        orderBy: [{ priority: "asc" }, { dueAt: "asc" }],
        take: limit,
      });
      const prioritized = rows.map((task) => ({
        id: task.id,
        title: task.title,
        priority: task.priority,
        status: task.status,
        dueAt: task.dueAt.toISOString(),
        projectIds: [],
        ...explainDailyPriority(task, now),
      })).sort((left, right) => right.score - left.score);
      return { ownerId: request.params.ownerId, generatedAt: now.toISOString(), tasks: prioritized };
    },
  );
}
