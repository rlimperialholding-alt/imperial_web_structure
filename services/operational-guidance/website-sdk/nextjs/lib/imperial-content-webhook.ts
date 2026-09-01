import { createHmac, timingSafeEqual } from "node:crypto";

export type ImperialPublishPayload = {
  event_id: string;
  action: "publish" | "unpublish" | "refresh";
  content_id: string;
  website_key: string;
  paths?: string[];
  tags?: string[];
  content: Record<string, unknown>;
};

export function verifyImperialSignature(
  rawBody: string,
  timestamp: string,
  signature: string,
  secret: string,
  toleranceSeconds = 300,
): boolean {
  const timestampNumber = Number(timestamp);
  if (!Number.isFinite(timestampNumber)) return false;
  if (Math.abs(Math.floor(Date.now() / 1000) - timestampNumber) > toleranceSeconds) {
    return false;
  }

  const digest = createHmac("sha256", secret)
    .update(`${timestamp}.${rawBody}`)
    .digest("hex");
  const expected = Buffer.from(`sha256=${digest}`);
  const received = Buffer.from(signature);
  return expected.length === received.length && timingSafeEqual(expected, received);
}
