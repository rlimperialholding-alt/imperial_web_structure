import type { FastifyInstance } from "fastify";
import type { IdentityVerifier } from "../security/identity-verifier.js";
import type { AuthService } from "../auth/service.js";

declare module "fastify" {
  interface FastifyRequest {
    verifiedActor?: {
      actorId: string;
      organizationId: string;
      roles: string[];
      permissions: string[];
      projectIds?: string[];
      sessionId?: string;
      isSystemAdmin?: boolean;
      isExecutive?: boolean;
    };
    authenticationSource?: "signed-service" | "bearer-session" | "cookie-session";
  }
}

export function registerIdentityHook(
  app: FastifyInstance,
  verifier: IdentityVerifier,
  auth: AuthService,
): void {
  app.addHook("preHandler", async (request) => {
    const path = request.url.split("?")[0] ?? request.url;
    if (isPublicPath(path, request.method)) {
      return;
    }

    const payload = request.headers["x-imperial-identity"];
    const signature = request.headers["x-imperial-identity-signature"];

    if (typeof payload === "string" && typeof signature === "string") {
      request.verifiedActor = verifier.verify(payload, signature);
      request.authenticationSource = "signed-service";
      return;
    }

    const bearer = parseBearer(request.headers.authorization);
    const cookieToken = parseCookie(
      request.headers.cookie,
      "imperial_session",
    );
    const token = bearer || cookieToken;
    if (!token) throw new Error("Authentication is required");
    const actor = await auth.authenticateSession(token);
    request.verifiedActor = actor;
    request.authenticationSource = bearer
      ? "bearer-session"
      : "cookie-session";

    if (
      !bearer &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method.toUpperCase())
    ) {
      const csrf = request.headers["x-csrf-token"];
      if (
        !actor.sessionId ||
        typeof csrf !== "string" ||
        !(await auth.verifyCsrf(actor.sessionId, csrf))
      ) {
        throw new Error("CSRF token is missing or invalid");
      }
    }
  });
}

function isPublicPath(path: string, method: string): boolean {
  if (path.startsWith("/health/") || path.startsWith("/docs")) return true;
  if (
    [
      "/v1/auth/bootstrap",
      "/v1/auth/login",
      "/v1/auth/mfa/verify",
      "/v1/auth/mfa/enroll/confirm",
      "/v1/auth/invitations/accept",
    ].includes(path)
  ) {
    return true;
  }
  return path === "/v1/webhooks/whatsapp" &&
    ["GET", "POST"].includes(method.toUpperCase());
}

function parseBearer(header: string | undefined): string {
  if (!header) return "";
  const [scheme, value] = header.split(/\s+/, 2);
  return scheme?.toLowerCase() === "bearer" ? value ?? "" : "";
}

function parseCookie(
  header: string | undefined,
  name: string,
): string {
  if (!header) return "";
  for (const part of header.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return "";
}
