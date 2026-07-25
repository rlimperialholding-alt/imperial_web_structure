import {describe,expect,it} from "vitest";
import {BillingoApiGateway,Psd2BankApiGateway,
 GenericCrmApiGateway} from "../src/connectors/business-api-gateways.js";
const response=(v:unknown)=>new Response(JSON.stringify(v),{status:200});
describe("business gateways",()=>{
 it("maps Billingo",async()=>{const g=new BillingoApiGateway("https://x.test",
  async()=>response({data:[{id:1,invoice_number:"I1",status:"PAID",
   gross_total:100,currency:"HUF",partner:{name:"C"},updated_at:"2026-07-24"}]}));
  expect((await g.listInvoiceChanges({accessToken:"x",externalAccountId:"p"}))
   .invoices[0]?.invoiceNumber).toBe("I1");});
 it("maps bank",async()=>{const g=new Psd2BankApiGateway("https://x.test",
  async()=>response({transactions:{booked:[{transactionId:"t",
   bookingDate:"2026-07-24",transactionAmount:{amount:"12.5",currency:"HUF"}}]}}));
  expect((await g.listTransactionChanges({accessToken:"x",externalAccountId:"a"}))
   .transactions[0]?.amount).toBe(12.5);});
 it("maps CRM",async()=>{const g=new GenericCrmApiGateway("https://x.test",
  async()=>response({activities:[{id:"a",subject:"Call",status:"OPEN"}]}));
  expect((await g.listActivityChanges({accessToken:"x",externalAccountId:"w"}))
   .activities[0]?.title).toBe("Call");});
  it("supports a custom CRM path and API-key header", async () => {
    let requestedUrl = "";
    let apiKey = "";
    const gateway = new GenericCrmApiGateway(
      "https://crm.test",
      async (input, init) => {
        requestedUrl = input;
        apiKey = String((init?.headers as Record<string, string>)["X-API-Key"]);
        return response({ items: [] });
      },
      {
        activitiesPath: "/internal/activities",
        authHeader: "X-API-Key",
        authScheme: "",
        workspaceQueryParameter: "tenant",
      },
    );
    await gateway.listActivityChanges({
      accessToken: "secret",
      externalAccountId: "imperial",
    });
    expect(requestedUrl).toContain("/internal/activities");
    expect(requestedUrl).toContain("tenant=imperial");
    expect(apiKey).toBe("secret");
  });

});
