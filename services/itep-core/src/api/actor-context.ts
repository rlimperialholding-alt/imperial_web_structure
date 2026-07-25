import type { FastifyRequest } from "fastify";
import type { ActorContext } from "../application/ports.js";

export function actorFromRequest(request: FastifyRequest): ActorContext {
  const actorId = header(request, "x-actor-id");
  const organizationId = header(request, "x-organization-id");
  const permissions = optionalHeader(request, "x-permissions")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  const roles = optionalHeader(request, "x-roles")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

  return { actorId, organizationId, permissions, roles };
}

function header(request: FastifyRequest, name: string): string {
  const value = request.headers[name];
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`Missing required header: ${name}`);
  }
  return value.trim();
}

function optionalHeader(request: FastifyRequest, name: string): string {
  const value = request.headers[name];
  return typeof value === "string" ? value : "";
}
