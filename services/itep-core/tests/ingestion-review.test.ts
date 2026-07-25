import { describe, expect, it } from "vitest";
import { IngestionReviewService } from "../src/ingestion/review-service.js";

describe("IngestionReviewService", () => {
  it("approves review item and creates task", async () => {
    let saved:any;
    const item:any={
      id:"r1",organizationId:"o",sourceEventId:"e1",status:"OPEN",createdAt:new Date(),
      candidate:{sourceEventId:"e1",organizationId:"o",source:"GMAIL",sourceExternalId:"m1",title:"Task",description:"D",issuerId:"digital-anne",priority:"P2",acceptanceCriteria:"Done",evidenceDescription:"Mail",confidence:.6,requiresHumanReview:true,reasons:[],sensitivity:"INTERNAL"}
    };
    const service=new IngestionReviewService(
      {async getById(){return item},async listOpen(){return[item]},async save(v){saved=v}},
      {async createFromCandidate(){return{taskId:"t1"}}},
      {now:()=>new Date("2026-07-24T08:00:00Z")},
    );
    const result=await service.approve("r1","human-anne",{assigneeId:"a1"});
    expect(result.taskId).toBe("t1");
    expect(saved.status).toBe("CONVERTED");
    expect(saved.candidate.assigneeId).toBe("a1");
  });
});
