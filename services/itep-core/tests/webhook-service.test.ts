import { describe, expect, it } from "vitest";
import { createHmac } from "node:crypto";
import { ConnectorWebhookService } from "../src/connectors/webhook-service.js";

describe("ConnectorWebhookService", () => {
  it("verifies signature and triggers sync", async () => {
    const body='{"ok":true}',secret="secret";
    const signature=createHmac("sha256",secret).update(body).digest("hex");
    let synced="";
    const service=new ConnectorWebhookService(
      {async findByExternalChannelId(){return{id:"s1",connectorAccountId:"c1",secret,status:"ACTIVE" as const}},async touch(){}},
      {async syncAccount(id: string){synced=id;return{received:0,ingested:0,ignored:0,failed:0,nextCheckpoint:{}}},async syncAll(){return[]}} as any,
      ()=>new Date(),
    );
    await service.receive({externalChannelId:"ch",rawBody:body,signature});
    expect(synced).toBe("c1");
  });
});
