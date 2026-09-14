import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";
import {
  ImperialPublishPayload,
  verifyImperialSignature,
} from "../../../../lib/imperial-content-webhook";

export async function POST(request: NextRequest) {
  const timestamp = request.headers.get("x-imperial-timestamp") ?? "";
  const signature = request.headers.get("x-imperial-signature") ?? "";
  const secret = process.env.IMPERIAL_CONTENT_WEBHOOK_SECRET ?? "";
  const rawBody = await request.text();

  if (!secret || !verifyImperialSignature(rawBody, timestamp, signature, secret)) {
    return NextResponse.json({ ok: false, error: "Invalid signature" }, { status: 401 });
  }

  let payload: ImperialPublishPayload;
  try {
    payload = JSON.parse(rawBody) as ImperialPublishPayload;
  } catch {
    return NextResponse.json({ ok: false, error: "Invalid JSON" }, { status: 400 });
  }

  // Persist or project payload.content into the website's local read model here when needed.
  // Headless sites can instead read the approved item directly from Directus.
  for (const tag of payload.tags ?? []) revalidateTag(tag, "max");
  for (const path of payload.paths ?? []) revalidatePath(path);

  return NextResponse.json({
    ok: true,
    event_id: payload.event_id,
    revalidated_paths: payload.paths ?? [],
    revalidated_tags: payload.tags ?? [],
  });
}
