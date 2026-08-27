import { describe, expect, it } from "vitest";
import { ConnectorSyncOrchestrator } from "../src/connectors/sync-orchestrator.js";

describe("ConnectorSyncOrchestrator", () => {
  it("persists checkpoint after successful sync", async () => {
    const saved:any[]=[];
    const account:any={id:"c1",organizationId:"o",kind:"GMAIL",scope:"GROUP",scopeKey:"GROUP",externalAccountId:"mail",displayName:"mail",status:"ACTIVE",scopes:[],createdAt:new Date(),updatedAt:new Date()};
    const orchestrator=new ConnectorSyncOrchestrator(
      {async getById(){return account},async save(v){saved.push(v)},async listActive(){return[account]}},
      {async get(){return null},async save(v){saved.push(v)}},
      {async getAccessToken(){return"token"},async invalidate(){}},
      {GMAIL:{async sync(){return{received:1,ingested:1,ignored:0,failed:0,nextCheckpoint:{historyId:"h2"}}}}},
      {async open(){}},
      {now:()=>new Date("2026-07-24T08:00:00Z")},
      {next:()=>"cp1"},
    );
    const result=await orchestrator.syncAccount("c1");
    expect(result.received).toBe(1);
    expect(saved.some(v=>v.historyId==="h2")).toBe(true);
  });

  it("marks reauth requirement on invalid token", async () => {
    let status="";
    const account:any={id:"c1",organizationId:"o",kind:"GMAIL",scope:"GROUP",scopeKey:"GROUP",externalAccountId:"mail",displayName:"mail",status:"ACTIVE",scopes:[],createdAt:new Date(),updatedAt:new Date()};
    const orchestrator=new ConnectorSyncOrchestrator(
      {async getById(){return account},async save(v){status=v.status},async listActive(){return[]}},
      {async get(){return null},async save(){}},
      {async getAccessToken(){throw new Error("401 unauthorized token")},async invalidate(){}},
      {GMAIL:{async sync(){return{received:0,ingested:0,ignored:0,failed:0,nextCheckpoint:{}}}}},
      {async open(){}},
      {now:()=>new Date()},
      {next:()=>"cp1"},
    );
    await expect(orchestrator.syncAccount("c1")).rejects.toThrow();
    expect(status).toBe("REAUTH_REQUIRED");
  });

  it("reports a partial sync as a failure and keeps the last success timestamp", async () => {
    const saved:any[]=[];
    const observed:any[]=[];
    const previousSuccess=new Date("2026-07-23T08:00:00Z");
    const account:any={id:"c1",organizationId:"o",kind:"CRM",scope:"GROUP",scopeKey:"GROUP",externalAccountId:"crm",displayName:"crm",status:"ACTIVE",scopes:[],createdAt:new Date(),updatedAt:new Date(),lastSuccessfulSyncAt:previousSuccess};
    const orchestrator=new ConnectorSyncOrchestrator(
      {async getById(){return account},async save(v){saved.push(v)},async listActive(){return[account]}},
      {async get(){return null},async save(v){saved.push(v)}},
      {async getAccessToken(){return"token"},async invalidate(){}},
      {CRM:{async sync(){return{received:3,ingested:2,ignored:0,failed:1,nextCheckpoint:{}}}}},
      {async open(){}},
      {now:()=>new Date("2026-07-24T08:00:00Z")},
      {next:()=>"cp1"},
      {async success(v){observed.push({type:"success",...v})},async failure(v){observed.push({type:"failure",...v})}},
    );

    await orchestrator.syncAccount("c1");

    const savedAccount=saved.find(v=>v.status==="DEGRADED");
    expect(savedAccount.lastSuccessfulSyncAt).toEqual(previousSuccess);
    expect(observed).toEqual([expect.objectContaining({type:"failure",errorMessage:"1 source events failed"})]);
  });
});
