import { describe, expect, it } from "vitest";
import { IntegrationControlRoomService } from "../src/integration-control-room/service.js";
import { PrismaIntegrationControlRoomRepository } from "../src/infrastructure/prisma-integration-control-room-repository.js";

function memoryRepository() {
  const snapshots = new Map<string, any>();
  const incidents = new Map<string, any>();
  const retries = new Map<string, any>();
  const deadLetters = new Map<string, any>();
  return {
    snapshots, incidents, retries, deadLetters,
    repo: {
      async listConnectorSnapshots(org:string){return [...snapshots.values()].filter(x=>x.organizationId===org)},
      async getConnectorSnapshot(org:string,id:string){return snapshots.get(`${org}:${id}`)??null},
      async saveConnectorSnapshot(v:any){snapshots.set(`${v.organizationId}:${v.connectorId}`,structuredClone(v))},
      async listOpenIncidents(org:string){return [...incidents.values()].filter(x=>x.organizationId===org&&x.status!=="RESOLVED")},
      async getIncident(id:string){return incidents.get(id)??null},
      async saveIncident(v:any){incidents.set(v.id,structuredClone(v))},
      async listDueRetries(now:Date,limit:number){return [...retries.values()].filter(x=>x.status==="PENDING"&&x.nextAttemptAt<=now).slice(0,limit)},
      async getRetry(id:string){return retries.get(id)??null},
      async saveRetry(v:any){retries.set(v.id,structuredClone(v))},
      async listDeadLetters(org:string){return [...deadLetters.values()].filter(x=>x.organizationId===org)},
      async getDeadLetter(id:string){return deadLetters.get(id)??null},
      async saveDeadLetter(v:any){deadLetters.set(v.id,structuredClone(v))},
    }
  };
}

describe("IntegrationControlRoomService", () => {
  it("opens a Human Anne incident after repeated connector failures", async () => {
    const mem=memoryRepository();
    const published:any[]=[];
    const service=new IntegrationControlRoomService(
      mem.repo as any,
      {async execute(){}},
      {async publish(v:any){published.push(v)}},
      ()=>new Date("2026-07-24T10:00:00Z"),
    );

    await service.recordConnectorFailure({
      organizationId:"imperial-holding",
      connectorId:"gmail-1",
      kind:"GMAIL",
      errorMessage:"temporary failure",
    });
    const second=await service.recordConnectorFailure({
      organizationId:"imperial-holding",
      connectorId:"gmail-1",
      kind:"GMAIL",
      errorMessage:"temporary failure",
    });

    expect(second.status).toBe("DEGRADED");
    expect(published).toHaveLength(1);
  });

  it("moves exhausted retries to dead letter", async () => {
    const mem=memoryRepository();
    const service=new IntegrationControlRoomService(
      mem.repo as any,
      {async execute(){throw new Error("provider down")}},
      {async publish(){}},
      ()=>new Date("2026-07-24T10:00:00Z"),
    );
    const retry=await service.enqueueRetry({
      organizationId:"imperial-holding",
      connectorId:"calendar-1",
      operation:"SYNC",
      payload:{},
      maxAttempts:1,
    });
    const result=await service.processDueRetries();
    expect(result.deadLettered).toBe(1);
    expect(mem.retries.get(retry.id).status).toBe("DEAD_LETTER");
    expect(mem.deadLetters.size).toBe(1);
  });

  it("persists cleared connector errors after a successful recovery", async () => {
    let updateData:any;
    const prisma={
      connectorOperationalSnapshot:{
        async upsert(input:any){
          updateData=input.update;
          return input.update;
        },
      },
    };
    const repository=new PrismaIntegrationControlRoomRepository(prisma as any);

    await repository.saveConnectorSnapshot({
      connectorId:"billingo-1",
      organizationId:"imperial-holding",
      kind:"BILLINGO",
      status:"HEALTHY",
      lastSuccessfulSyncAt:new Date("2026-07-31T10:00:00Z"),
      lastAttemptAt:new Date("2026-07-31T10:00:00Z"),
      consecutiveFailures:0,
      pendingRetries:0,
      deadLetterCount:0,
      reauthRequired:false,
      updatedAt:new Date("2026-07-31T10:00:00Z"),
    });

    expect(updateData.lastErrorCode).toBeNull();
    expect(updateData.lastErrorMessage).toBeNull();
    expect(updateData.rateLimitedUntil).toBeNull();
  });
});
