import { getRuntimeValue } from "@/db";

const FORWARDED_HEADERS = [
  "authorization",
  "cookie",
  "content-type",
  "user-agent",
  "x-bootstrap-token",
  "x-csrf-token",
] as const;

export type InternalUser = {
  id: string;
  email: string;
  displayName: string;
  isSystemAdmin: boolean;
  isExecutive: boolean;
  mfaEnabled: boolean;
  activeOrganizationId: string;
  activeRoles: string[];
  activePermissions: string[];
  activeProjectIds: string[];
  memberships: Array<{
    organizationId: string;
    jobRole: string;
    projectIds: string[];
    permissionGrants: string[];
    permissionDenials: string[];
  }>;
};

export async function callIdentityApi(
  path: string,
  request: Request,
  method = request.method,
  forwardBody = true,
): Promise<Response> {
  const configuredBaseUrl =
    (await getRuntimeValue("ITEP_BASE_URL"))?.trim() ||
    "http://127.0.0.1:3000";
  const baseUrl = new URL(configuredBaseUrl);
  const upstreamPath = path.startsWith("/") ? path : `/${path}`;
  const upstreamUrl = new URL(upstreamPath, `${baseUrl.origin}/`);
  upstreamUrl.search = new URL(request.url).search;

  const headers = new Headers();
  for (const name of FORWARDED_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("accept", "application/json");
  headers.set("x-forwarded-for", clientAddress(request));

  const upperMethod = method.toUpperCase();
  const body =
    !forwardBody || ["GET", "HEAD"].includes(upperMethod)
      ? undefined
      : await request.arrayBuffer();
  return fetch(upstreamUrl, {
    method: upperMethod,
    headers,
    body: body && body.byteLength > 0 ? body : undefined,
    redirect: "manual",
    cache: "no-store",
  });
}

export async function verifyInternalUser(
  request: Request,
): Promise<InternalUser> {
  const method = request.method.toUpperCase();
  const isRead = ["GET", "HEAD", "OPTIONS"].includes(method);
  const verification = await callIdentityApi(
    isRead ? "/v1/auth/me" : "/v1/auth/csrf/verify",
    request,
    isRead ? "GET" : "POST",
    false,
  );
  if (!verification.ok) {
    throw new Response("Azonosítás szükséges.", {
      status: verification.status === 403 ? 403 : 401,
    });
  }
  if (isRead) return (await verification.json()) as InternalUser;

  const identityResponse = await callIdentityApi(
    "/v1/auth/me",
    request,
    "GET",
    false,
  );
  if (!identityResponse.ok) {
    throw new Response("Azonosítás szükséges.", { status: 401 });
  }
  return (await identityResponse.json()) as InternalUser;
}

export async function proxyIdentityResponse(
  upstreamPath: string,
  request: Request,
): Promise<Response> {
  const upstream = await callIdentityApi(upstreamPath, request);
  const headers = new Headers();
  headers.set(
    "content-type",
    upstream.headers.get("content-type") ?? "application/json; charset=utf-8",
  );
  headers.set("cache-control", "no-store");
  const setCookie = upstream.headers.get("set-cookie");
  if (setCookie) headers.set("set-cookie", setCookie);
  return new Response(upstream.body, {
    status: upstream.status,
    headers,
  });
}

function clientAddress(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0]?.trim() || "unknown";
  return request.headers.get("cf-connecting-ip")?.trim() || "unknown";
}
