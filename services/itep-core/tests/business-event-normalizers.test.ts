import {describe,expect,it} from "vitest";
import {normalizeBankTransaction,normalizeBillingoInvoice,
 normalizeCrmActivity,normalizeMarketingMetric} from "../src/connectors/business-event-normalizers.js";
const now=new Date("2026-07-24T12:00:00Z");
describe("business event normalizers",()=>{
 it("maps overdue invoice",()=>{const e=normalizeBillingoInvoice("org",{
  invoiceId:"1",invoiceNumber:"INV-1",customerName:"Client",status:"OVERDUE",
 grossAmount:1000,currency:"HUF",updatedAt:now},now);
  expect(e.metadata.eventType).toBe("PAYMENT_OVERDUE");
  expect(e.metadata.accessMode).toBe("READ_ONLY");});
 it("maps incoming bank transaction",()=>{const e=normalizeBankTransaction("org",{
  transactionId:"t1",accountId:"a1",bookingDate:now,amount:100,
  currency:"HUF",status:"BOOKED"},now);
  expect(e.metadata.eventType).toBe("PAYMENT_RECEIVED");});
 it("maps lead",()=>{const e=normalizeCrmActivity("org",{
  activityId:"c1",type:"LEAD",title:"Új lead",occurredAt:now,status:"OPEN"},now);
 expect(e.metadata.eventType).toBe("LEAD_CREATED");});
 it("stores marketing metrics as a read-only snapshot",()=>{const e=normalizeMarketingMetric("org",{
  organizationId:"org",provider:"META_ADS",accountId:"a1",campaignId:"c1",
  campaignName:"Lead",dateStart:"2026-07-24",dateStop:"2026-07-24",
  impressions:100,clicks:10,spend:1200,currency:"HUF",conversions:2,
  updatedAt:now},now);
  expect(e.metadata.accessMode).toBe("READ_ONLY");
  expect(e.labels).toContain("MARKETING");});
});
