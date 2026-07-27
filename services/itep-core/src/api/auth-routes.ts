import type {
  FastifyInstance,
  FastifyReply,
  FastifyRequest,
} from "fastify";
import { z } from "zod";
import type { AuthService, SessionResult } from "../auth/service.js";
import type { AppConfig } from "../config/env.js";
import { actorFromRequest } from "./actor-context.js";

const bootstrapSchema = z.object({
  email: z.string().email(),
  displayName: z.string().trim().min(2).max(200),
  password: z.string().min(14).max(128),
  organizationId: z.string().trim().min(2).max(100).optional(),
  organizationName: z.string().trim().min(2).max(200).optional(),
});
const inviteAcceptSchema = z.object({
  invitationToken: z.string().min(20),
  password: z.string().min(14).max(128),
});
const enrollSchema = z.object({
  enrollmentToken: z.string().min(20),
  code: z.string().regex(/^\d{6}$/),
});
const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1).max(128),
  organizationId: z.string().trim().min(2).max(100).optional(),
});
const mfaSchema = z
  .object({
    challengeToken: z.string().min(20),
    code: z.string().regex(/^\d{6}$/).optional(),
    recoveryCode: z.string().min(8).max(32).optional(),
  })
  .refine((value) => Boolean(value.code) !== Boolean(value.recoveryCode), {
    message: "Provide exactly one authentication code",
  });
const switchSchema = z.object({
  organizationId: z.string().trim().min(2).max(100),
});

export function registerAuthRoutes(
  app: FastifyInstance,
  auth: AuthService,
  config: AppConfig,
): void {
  app.post("/v1/auth/bootstrap", async (request, reply) => {
    const bootstrapToken = request.headers["x-bootstrap-token"];
    if (typeof bootstrapToken !== "string") {
      throw new Error("Bootstrap token is required");
    }
    return reply.code(201).send(
      await auth.bootstrap({
        bootstrapToken,
        ...bootstrapSchema.parse(request.body),
      }),
    );
  });

  app.post("/v1/auth/invitations/accept", async (request) =>
    auth.acceptInvitation(inviteAcceptSchema.parse(request.body)),
  );

  app.post("/v1/auth/mfa/enroll/confirm", async (request, reply) => {
    const result = await auth.confirmMfaEnrollment(
      enrollSchema.parse(request.body),
      securityContext(request),
    );
    setSessionCookie(reply, result, config);
    return result;
  });

  app.post("/v1/auth/login", async (request) =>
    auth.login(loginSchema.parse(request.body), securityContext(request)),
  );

  app.post("/v1/auth/mfa/verify", async (request, reply) => {
    const result = await auth.verifyMfa(
      mfaSchema.parse(request.body),
      securityContext(request),
    );
    setSessionCookie(reply, result, config);
    return result;
  });

  app.get("/v1/auth/me", async (request) =>
    auth.currentUser(actorFromRequest(request)),
  );

  app.get("/v1/auth/csrf", async (request) =>
    auth.issueCsrfToken(actorFromRequest(request)),
  );

  app.post("/v1/auth/csrf/verify", async (_request, reply) =>
    reply.code(204).send(),
  );

  app.post("/v1/auth/switch-organization", async (request, reply) => {
    const actor = actorFromRequest(request);
    const { organizationId } = switchSchema.parse(request.body);
    const result = await auth.switchOrganization(
      actor,
      organizationId,
      securityContext(request),
    );
    setSessionCookie(reply, result, config);
    return result;
  });

  app.post("/v1/auth/logout", async (request, reply) => {
    const actor = actorFromRequest(request);
    if (actor.sessionId) await auth.logout(actor.sessionId);
    reply.header(
      "set-cookie",
      "imperial_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
    );
    return reply.code(204).send();
  });
}

export function securityContext(request: FastifyRequest) {
  return {
    ip: request.ip,
    userAgent:
      typeof request.headers["user-agent"] === "string"
        ? request.headers["user-agent"]
        : undefined,
    requestId: request.id,
  };
}

function setSessionCookie(
  reply: FastifyReply,
  result: SessionResult,
  config: AppConfig,
): void {
  const maxAge = Math.max(
    0,
    Math.floor((result.expiresAt.getTime() - Date.now()) / 1000),
  );
  const secure = config.AUTH_COOKIE_SECURE ? "; Secure" : "";
  reply.header(
    "set-cookie",
    `imperial_session=${encodeURIComponent(
      result.sessionToken,
    )}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAge}${secure}`,
  );
}
