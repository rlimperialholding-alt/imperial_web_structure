import {describe,expect,it} from "vitest";
import {normalizeBankTransaction,normalizeBillingoInvoice,
 normalizeCrmActivity} from "../src/connectors/business-event-normalizers.js";
const now=new Date("2026-07-24T12:00:00Z");
describe("business event normalizers",()=>{
 it("maps overdue invoice",()=>{const e=normalizeBillingoInvoice("org",{
  invoiceId:"1",invoiceNumber:"INV-1",customerName:"Client",status:"OVERDUE",
  grossAmount:1000,currency:"HUF",updatedAt:now},now);
  expect(e.metadata.eventType).toBe("PAYMENT_OVERDUE");});
 it("maps incoming bank transaction",()=>{const e=normalizeBankTransaction("org",{
  transactionId:"t1",accountId:"a1",bookingDate:now,amount:100,
  currency:"HUF",status:"BOOKED"},now);
  expect(e.metadata.eventType).toBe("PAYMENT_RECEIVED");});
 it("maps lead",()=>{const e=normalizeCrmActivity("org",{
  activityId:"c1",type:"LEAD",title:"Új lead",occurredAt:now,status:"OPEN"},now);
  expect(e.metadata.eventType).toBe("LEAD_CREATED");});
});
