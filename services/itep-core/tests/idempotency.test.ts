import { describe, expect, it } from "vitest";
import { IdempotencyService } from "../src/security/idempotency.js";

describe("IdempotencyService", () => {
  it("replays a completed operation", async () => {
    const records=new Map<string,any>();
    const repo={
      async get(scope:string,key:string){return records.get(`${scope}:${key}`)??null},
      async create(v:any){records.set(`${v.scope}:${v.key}`,v)},
      async complete(v:any){records.set(`${v.scope}:${v.key}`,{...records.get(`${v.scope}:${v.key}`),...v})},
    };
    const service=new IdempotencyService(repo,()=>new Date("2026-07-24T08:00:00Z"));
    expect((await service.begin({scope:"task.create",key:"k1",requestHash:"h1"})).mode).toBe("NEW");
    await service.complete({scope:"task.create",key:"k1",responseStatus:201,responseBody:{id:"t1"}});
    const replay=await service.begin({scope:"task.create",key:"k1",requestHash:"h1"});
    expect(replay.mode).toBe("REPLAY");
    if(replay.mode==="REPLAY") expect(replay.body).toEqual({id:"t1"});
  });
});
