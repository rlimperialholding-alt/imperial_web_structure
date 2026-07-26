import type { FastifyInstance } from "fastify";
import type { Prisma, PrismaClient } from "@prisma/client";
import { z } from "zod";
import { evaluateDigitalActionRisk } from "../digital-project-managers/policy.js";
import { actorFromRequest } from "./actor-context.js";

const assignmentSchema = z.object({
  managerId: z.string().min(1),
});

const actionSchema = z.object({
  projectId: z.string().min(1),
  managerId: z.string().min(1).optional(),
  action: z.string().min(3),
  risk: z.enum(["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7"]),
  context: z.record(z.unknown()).default({}),
});

export function registerDigitalProjectManagerRoutes(
  app: FastifyInstance,
  prisma: PrismaClient,
) {
  app.get("/v1/digital-project-managers", async (request) => {
    const actor = actorFromRequest(request);
    return {
      managers: await prisma.digitalProjectManager.findMany({
        where: { organizationId: actor.organizationId },
        orderBy: { displayName: "asc" },
      }),
    };
  });

  app.get<{ Params: { projectId: string } }>(
    "/v1/digital-project-managers/projects/:projectId",
    async (request, reply) => {
      const actor = actorFromRequest(request);
      const assignment = await prisma.digitalProjectAssignment.findUnique({
        where: {
          organizationId_projectId: {
            organizationId: actor.organizationId,
            projectId: request.params.projectId,
          },
        },
        include: { manager: true },
      });
      if (!assignment) return reply.code(404).send({ error: "ASSIGNMENT_NOT_FOUND" });
      return assignment;
    },
  );

  app.put<{ Params: { projectId: string } }>(
    "/v1/digital-project-managers/projects/:projectId",
    async (request) => {
      const actor = actorFromRequest(request);
      assertCanManage(actor.roles, actor.permissions);
      const { managerId } = assignmentSchema.parse(request.body);
      const manager = await prisma.digitalProjectManager.findFirst({
        where: {
          id: managerId,
          organizationId: actor.organizationId,
          status: "ACTIVE",
        },
      });
      if (!manager) throw new Error("Active digital project manager not found");
      const assignment = await prisma.digitalProjectAssignment.upsert({
        where: {
          organizationId_projectId: {
            organizationId: actor.organizationId,
            projectId: request.params.projectId,
          },
        },
        create: {
          organizationId: actor.organizationId,
          projectId: request.params.projectId,
          managerId,
          assignedBy: actor.actorId,
        },
        update: {
          managerId,
          assignedBy: actor.actorId,
          assignedAt: new Date(),
        },
        include: { manager: true },
      });
      await prisma.digitalPmAuditEvent.create({
        data: {
          organizationId: actor.organizationId,
          actorId: actor.actorId,
          eventType: "PROJECT_MANAGER_ASSIGNED",
          projectId: request.params.projectId,
          managerId,
          payload: { managerName: manager.displayName },
        },
      });
      return assignment;
    },
  );

  app.post("/v1/digital-project-managers/actions/evaluate", async (request) => {
    const actor = actorFromRequest(request);
    assertCanManage(actor.roles, actor.permissions);
    const body = actionSchema.parse(request.body);
    if (body.managerId) {
      const manager = await prisma.digitalProjectManager.findFirst({
        where: {
          id: body.managerId,
          organizationId: actor.organizationId,
          status: "ACTIVE",
        },
      });
      if (!manager) throw new Error("Active digital project manager not found");
    }
    const result = evaluateDigitalActionRisk(body.risk);
    await prisma.digitalPmAuditEvent.create({
      data: {
        organizationId: actor.organizationId,
        actorId: actor.actorId,
        eventType: "ACTION_RISK_EVALUATED",
        projectId: body.projectId,
        managerId: body.managerId,
        actionRisk: body.risk,
        decision: result.decision,
        payload: {
          action: body.action,
          context: body.context,
          executionAllowed: result.executionAllowed,
        } as Prisma.InputJsonValue,
      },
    });
    return { ...result, action: body.action, projectId: body.projectId };
  });

  app.get("/v1/digital-project-managers/audit", async (request) => {
    const actor = actorFromRequest(request);
    return {
      events: await prisma.digitalPmAuditEvent.findMany({
        where: { organizationId: actor.organizationId },
        orderBy: { occurredAt: "desc" },
        take: 200,
      }),
    };
  });
}

function assertCanManage(roles: string[], permissions: string[]) {
  if (
    roles.includes("SYSTEM") ||
    roles.includes("ADMIN") ||
    permissions.includes("digital-pm.manage")
  ) return;
  throw new Error("digital-pm.manage permission is required");
}

