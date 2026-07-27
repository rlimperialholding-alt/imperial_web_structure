import { proxyIdentityResponse } from "@/lib/itep-auth";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, context: RouteContext) {
  const segments = (await context.params).path;
  const path = segments.join("/");
  if (
    path !== "conversations" &&
    !/^conversations\/[^/]+(?:\/messages)?$/.test(path) &&
    !/^messages\/[^/]+\/(?:approve|reject)$/.test(path)
  ) {
    return Response.json({ error: "Ismeretlen WhatsApp-művelet." }, { status: 404 });
  }
  return proxyIdentityResponse(`/v1/whatsapp/${path}`, request);
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
