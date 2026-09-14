import { describe, expect, it } from "vitest";
import { calculateAuditHash, verifyAuditChain } from "../src/security/audit-integrity.js";

describe("audit integrity", () => {
  it("verifies a valid chain and detects tampering", () => {
    const first:any={id:"1",taskId:"t",eventType:"A",actorId:"u",occurredAt:new Date("2026-07-24T08:00:00Z"),sequence:1n,payload:{a:1}};
    first.hash=calculateAuditHash(first);
    const second:any={id:"2",taskId:"t",eventType:"B",actorId:"u",occurredAt:new Date("2026-07-24T09:00:00Z"),sequence:2n,payload:{b:2},previousHash:first.hash};
    second.hash=calculateAuditHash(second);
    expect(verifyAuditChain([first,second]).valid).toBe(true);
    second.payload={b:3};
    expect(verifyAuditChain([first,second]).valid).toBe(false);
  });
});
