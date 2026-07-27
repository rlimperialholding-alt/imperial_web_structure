import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { AuthService } from "../auth/service.js";
import { actorFromRequest } from "./actor-context.js";

const jobRoleSchema = z.enum([
  "SYSTEM_ADMIN",
  "EXECUTIVE",
  "FINANCE",
  "HR",
  "SALES",
  "MARKETING",
  "PROJECT_MANAGER",
  "ENGINEERING",
  "LEGAL",
  "PROCUREMENT",
  "WAREHOUSE",
  "SUBCONTRACTOR",
  "CUSTOMER",
]);
const membershipSchema = z.object({
  organizationId: z.string().min(2).max(100),
  jobRole: jobRoleSchema,
  projectIds: z.array(z.string().min(1).max(200)).max(500).default([]),
  permissionGrants: z.array(z.string().min(1).max(200)).max(100).default([]),
  permissionDenials: z.array(z.string().min(1).max(200)).max(100).default([]),
});
const inviteSchema = z.object({
  email: z.string().email(),
  displayName: z.string().trim().min(2).max(200),
  isExecutive: z.boolean().default(false),
  memberships: z.array(membershipSchema).max(100),
});
const organizationSchema = z.object({
  id: z.string().regex(/^[a-z0-9][a-z0-9-]{1,99}$/),
  displayName: z.string().trim().min(2).max(200),
  taxNumber: z.string().trim().max(50).optional(),
});

export function registerAdminAuthRoutes(
  app: FastifyInstance,
  auth: AuthService,
): void {
  app.get("/v1/admin/job-role-templates", async (request) => {
    const actor = actorFromRequest(request);
    if (
      !actor.isSystemAdmin &&
      !actor.isExecutive &&
      !actor.permissions.includes("*")
    ) {
      throw new Error("Administrator access required");
    }
    return auth.jobRoleTemplates();
  });

  app.get("/v1/admin/users", async (request) =>
    auth.listUsers(actorFromRequest(request)),
  );

  app.get("/v1/admin/organizations", async (request) =>
    auth.listOrganizations(actorFromRequest(request)),
  );

  app.post("/v1/admin/users/invite", async (request, reply) =>
    reply.code(201).send(
      await auth.inviteUser(
        actorFromRequest(request),
        inviteSchema.parse(request.body),
      ),
    ),
  );

  app.patch<{ Params: { id: string } }>(
    "/v1/admin/users/:id/access",
    async (request) =>
      auth.updateUserAccess(
        actorFromRequest(request),
        request.params.id,
        z.object({
          isExecutive: z.boolean().default(false),
          memberships: z.array(membershipSchema).max(100),
        }).parse(request.body),
      ),
  );

  app.post<{ Params: { id: string } }>(
    "/v1/admin/users/:id/recovery",
    async (request, reply) =>
      reply.code(201).send(
        await auth.createRecoveryInvitation(
          actorFromRequest(request),
          request.params.id,
        ),
      ),
  );

  app.post("/v1/admin/organizations", async (request, reply) =>
    reply.code(201).send(
      await auth.createOrganization(
        actorFromRequest(request),
        organizationSchema.parse(request.body),
      ),
    ),
  );
}
