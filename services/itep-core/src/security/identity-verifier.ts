import { createHmac, timingSafeEqual } from "node:crypto";
import type { ActorContext } from "../application/ports.js";

export interface SignedIdentityPayload {
  actorId: string;
  organizationId: string;
  roles: string[];
  permissions: string[];
  issuedAt: number;
  expiresAt: number;
  nonce: string;
}

export class IdentityVerifier {
  constructor(
    private readonly secret: string,
    private readonly now: () => Date,
    private readonly maxClockSkewSeconds = 60,
  ) {}

  verify(payloadBase64: string, signature: string): ActorContext {
    const expected = createHmac("sha256", this.secret)
      .update(payloadBase64)
      .digest("hex");
    const received = signature.replace(/^sha256=/, "");

    if (
      expected.length !== received.length ||
      !timingSafeEqual(
        Buffer.from(expected, "utf8"),
        Buffer.from(received, "utf8"),
      )
    ) {
      throw new Error("Invalid identity signature");
    }

    const payload = JSON.parse(
      Buffer.from(payloadBase64, "base64url").toString("utf8"),
    ) as SignedIdentityPayload;

    const nowSeconds = Math.floor(this.now().getTime() / 1000);
    if (payload.issuedAt > nowSeconds + this.maxClockSkewSeconds) {
      throw new Error("Identity token issued in the future");
    }
    if (payload.expiresAt < nowSeconds - this.maxClockSkewSeconds) {
      throw new Error("Identity token expired");
    }
    if (!payload.actorId || !payload.organizationId || !payload.nonce) {
      throw new Error("Identity payload is incomplete");
    }

    return {
      actorId: payload.actorId,
      organizationId: payload.organizationId,
      roles: payload.roles ?? [],
      permissions: payload.permissions ?? [],
    };
  }
}
