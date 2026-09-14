import { describe, expect, it } from "vitest";
import { createHmac } from "node:crypto";
import { IdentityVerifier } from "../src/security/identity-verifier.js";

describe("IdentityVerifier", () => {
  it("accepts a valid signed identity", () => {
    const secret="12345678901234567890123456789012";
    const payload=Buffer.from(JSON.stringify({
      actorId:"u1",organizationId:"o1",roles:["DIRECTOR"],
      permissions:["task.create"],issuedAt:1000,expiresAt:2000,nonce:"n1"
    })).toString("base64url");
    const signature=createHmac("sha256",secret).update(payload).digest("hex");
    const actor=new IdentityVerifier(secret,()=>new Date(1500*1000)).verify(payload,signature);
    expect(actor.actorId).toBe("u1");
    expect(actor.permissions).toContain("task.create");
  });

  it("rejects an expired identity", () => {
    const secret="12345678901234567890123456789012";
    const payload=Buffer.from(JSON.stringify({
      actorId:"u1",organizationId:"o1",roles:[],permissions:[],
      issuedAt:1000,expiresAt:1100,nonce:"n1"
    })).toString("base64url");
    const signature=createHmac("sha256",secret).update(payload).digest("hex");
    expect(()=>new IdentityVerifier(secret,()=>new Date(2000*1000),0).verify(payload,signature)).toThrow("expired");
  });
});
