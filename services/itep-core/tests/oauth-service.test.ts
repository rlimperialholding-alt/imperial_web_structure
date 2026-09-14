import { describe, expect, it } from "vitest";
import { ConnectorOAuthService } from "../src/connectors/oauth-service.js";

describe("ConnectorOAuthService", () => {
  it("creates an account after callback", async () => {
    const saved:any[]=[];
    const service=new ConnectorOAuthService(
      {async getById(){return null},async save(v){saved.push(v)},async listActive(){return[]}},
      {GMAIL:{
        async buildAuthorizationUrl(){return"https://accounts.example/auth"},
        async exchangeCode(){return{accessToken:"a",refreshToken:"r",externalAccountId:"mail@example.com",displayName:"Mail",grantedScopes:["gmail.readonly"]}}
      },CALENDAR:{} as any},
      {async save(){},async consume(){return{organizationId:"o",kind:"GMAIL",redirectUri:"https://app/cb",requestedScopes:["gmail.readonly"],createdBy:"u"}}},
      {async store(v){saved.push(v)},async delete(){}},
      {now:()=>new Date("2026-07-24T08:00:00Z")},
      {next:(()=>{let i=0;return()=>`id-${++i}`})()},
    );
    const result=await service.complete({state:"s",code:"c"});
    expect(result.kind).toBe("GMAIL");
    expect(saved.some(v=>v.status==="ACTIVE")).toBe(true);
  });
});
