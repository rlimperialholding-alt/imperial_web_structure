import { proxyIdentityResponse } from "@/lib/itep-auth";

const PUBLIC_AUTH_PATHS = new Set([
  "login",
  "mfa/verify",
  "mfa/enroll/confirm",
  "invitations/accept",
  "logout",
  "me",
  "csrf",
  "switch-organization",
]);
const ADMIN_PATHS = new Set([
  "admin/job-role-templates",
  "admin/organizations",
  "admin/users",
  "admin/users/invite",
]);

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, context: RouteContext) {
  const path = (await context.params).path.join("/");
  if (
    !PUBLIC_AUTH_PATHS.has(path) &&
    !ADMIN_PATHS.has(path) &&
    !/^admin\/users\/[^/]+\/(recovery|access)$/.test(path)
  ) {
    return Response.json(
      { error: "Ismeretlen belépési művelet." },
      { status: 404 },
    );
  }
  const upstreamPath = path.startsWith("admin/")
    ? `/v1/${path}`
    : `/v1/auth/${path}`;
  return proxyIdentityResponse(upstreamPath, request);
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
