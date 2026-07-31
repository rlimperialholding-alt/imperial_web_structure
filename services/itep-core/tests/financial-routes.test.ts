import Fastify from "fastify";
import { describe, expect, it } from "vitest";
import { registerFinancialRoutes } from "../src/api/financial-routes.js";

function appWith(permissions:string[]) {
  const app=Fastify();
  app.addHook("preHandler",async request=>{
    request.verifiedActor={
      actorId:"finance-user",
      organizationId:"imperial-holding",
      roles:["FINANCE"],
      permissions,
    };
  });
  const invoice={
    id:"SRC-1",
    occurredAt:new Date("2026-07-30T00:00:00Z"),
    labels:["BILLINGO","INCOMING_INVOICE","UNPAID"],
    metadata:{
      invoiceNumber:"INV-1",
      partnerName:"Minta Partner Kft.",
      taxNumber:"12345678",
      issueDate:"2026-07-30",
      dueDate:"2026-08-15",
      paymentDate:null,
      netAmount:1000,
      vatAmount:270,
      grossAmount:1270,
      currency:"HUF",
      sourceRowHash:"abc",
    },
  };
  const prisma={
    sourceEvent:{
      async findMany(input:any){
        return input.take ? [invoice] : [{
          labels:invoice.labels,
          metadata:invoice.metadata,
        }];
      },
    },
  };
  registerFinancialRoutes(app,prisma as any);
  return app;
}

describe("financial routes",()=>{
  it("returns a paginated incoming invoice projection",async()=>{
    const app=appWith(["financial:read"]);
    const response=await app.inject({
      method:"GET",
      url:"/v1/financial/incoming-invoices?page=1&pageSize=50",
    });
    expect(response.statusCode).toBe(200);
    const body=response.json();
    expect(body.total).toBe(1);
    expect(body.summary.unpaid).toBe(1);
    expect(body.summary.currencyTotals.HUF.grossAmount).toBe(1270);
    expect(body.items[0]).toMatchObject({
      invoiceNumber:"INV-1",
      partnerName:"Minta Partner Kft.",
      paymentStatus:"UNPAID",
    });
    await app.close();
  });

  it("requires financial read permission",async()=>{
    const app=appWith([]);
    const response=await app.inject({
      method:"GET",
      url:"/v1/financial/incoming-invoices",
    });
    expect(response.statusCode).toBe(500);
    expect(response.body).toContain("financial:read permission required");
    await app.close();
  });
});
