import { buildSourceFingerprint } from "../ingestion/fingerprint.js";
import type { SourceEvent } from "../ingestion/types.js";

export interface BillingoInvoiceEvent {
  invoiceId: string; invoiceNumber: string; projectId?: string;
  customerName: string; customerEmail?: string; status: string;
  grossAmount: number; currency: string; dueAt?: Date; paidAt?: Date;
  updatedAt: Date;
}
export interface BankTransactionEvent {
  transactionId: string; accountId: string; projectId?: string;
  bookingDate: Date; amount: number; currency: string;
  counterpartyName?: string; counterpartyAccount?: string;
  remittanceInformation?: string; status: string;
}
export interface CrmActivityEvent {
  activityId: string; projectId?: string; leadId?: string; dealId?: string;
  type: string; title: string; description?: string; ownerId?: string;
  ownerEmail?: string; contactEmail?: string; dueAt?: Date;
  occurredAt: Date; status: string; priority?: string;
}
export interface MarketingMetricEvent {
  organizationId: string;
  provider: "META_ADS" | "GOOGLE_ADS";
  accountId: string;
  campaignId: string;
  campaignName: string;
  campaignStatus?: string;
  dateStart: string;
  dateStop: string;
  impressions: number;
  clicks: number;
  spend: number;
  currency?: string;
  conversions: number;
  updatedAt: Date;
}

export interface ConnectorEventContext {
  connectorAccountId: string;
  legalEntityId?: string;
}

export function normalizeBillingoInvoice(
  organizationId: string,
  event: BillingoInvoiceEvent,
  receivedAt: Date,
  context?: ConnectorEventContext,
): SourceEvent {
  const namespace = context?.connectorAccountId
    ? `${context.connectorAccountId}:`
    : "";
  const externalId =
    `billingo:${namespace}${event.invoiceId}:${event.updatedAt.toISOString()}`;
  return {
    id: sourceId(
      "BILLINGO",
      context?.connectorAccountId,
      event.invoiceId,
      event.updatedAt.getTime(),
    ),
    organizationId,
    ...(context?.legalEntityId
      ? { legalEntityId: context.legalEntityId }
      : {}),
    source: "WEBHOOK", externalId,
    occurredAt: event.updatedAt, receivedAt, actorId: "digital-anne",
    subject: `Számla ${event.invoiceNumber}: ${event.status}`,
    body: `${event.customerName}; ${event.grossAmount} ${event.currency}; ` +
      `határidő: ${event.dueAt?.toISOString() ?? "nincs"}`,
    participants: event.customerEmail ? [event.customerEmail] : [],
    labels: ["BILLINGO", "FINANCIAL", event.status.toUpperCase()],
    metadata: {
      provider: "BILLINGO", eventType: invoiceEventType(event.status),
      accessMode: "READ_ONLY",
      connectorAccountId: context?.connectorAccountId,
      legalEntityId: context?.legalEntityId,
      invoiceId: event.invoiceId, invoiceNumber: event.invoiceNumber,
      projectId: event.projectId, status: event.status,
      grossAmount: event.grossAmount, currency: event.currency,
      dueAt: event.dueAt?.toISOString(), paidAt: event.paidAt?.toISOString(),
    },
    status: "NORMALIZED",
    fingerprint: buildSourceFingerprint({
      organizationId, source: "WEBHOOK", externalId,
      subject: `${event.invoiceNumber}:${event.status}`,
      occurredAt: event.updatedAt,
    }),
  };
}

export function normalizeBankTransaction(
  organizationId: string,
  event: BankTransactionEvent,
  receivedAt: Date,
  context?: ConnectorEventContext,
): SourceEvent {
  const namespace = context?.connectorAccountId
    ? `${context.connectorAccountId}:`
    : "";
  const externalId =
    `bank:${namespace}${event.accountId}:${event.transactionId}`;
  return {
    id: sourceId("BANK", context?.connectorAccountId, event.transactionId),
    organizationId,
    ...(context?.legalEntityId
      ? { legalEntityId: context.legalEntityId }
      : {}),
    source: "WEBHOOK", externalId, occurredAt: event.bookingDate,
    receivedAt, actorId: "digital-anne",
    subject: `Banki tranzakció: ${event.amount} ${event.currency}`,
    body: `${event.counterpartyName ?? "Ismeretlen partner"} – ` +
      `${event.remittanceInformation ?? "közlemény nélkül"}`,
    participants: [], labels: ["BANK", "FINANCIAL", event.status.toUpperCase()],
    metadata: {
      provider: "BANK",
      eventType: event.amount >= 0 ? "PAYMENT_RECEIVED" : "PAYMENT_SENT",
      connectorAccountId: context?.connectorAccountId,
      legalEntityId: context?.legalEntityId,
      transactionId: event.transactionId, accountId: event.accountId,
      projectId: event.projectId, amount: event.amount,
      currency: event.currency, status: event.status,
      bookingDate: event.bookingDate.toISOString(),
      counterpartyName: event.counterpartyName,
      counterpartyAccount: event.counterpartyAccount,
      remittanceInformation: event.remittanceInformation,
    },
    status: "NORMALIZED",
    fingerprint: buildSourceFingerprint({
      organizationId, source: "WEBHOOK", externalId,
      subject: `${event.amount}:${event.currency}`,
      occurredAt: event.bookingDate,
    }),
  };
}

export function normalizeCrmActivity(
  organizationId: string,
  event: CrmActivityEvent,
  receivedAt: Date,
  context?: ConnectorEventContext,
): SourceEvent {
  const namespace = context?.connectorAccountId
    ? `${context.connectorAccountId}:`
    : "";
  const externalId = `crm:${namespace}${event.activityId}`;
  return {
    id: sourceId("CRM", context?.connectorAccountId, event.activityId),
    organizationId,
    ...(context?.legalEntityId
      ? { legalEntityId: context.legalEntityId }
      : {}),
    source: "WEBHOOK", externalId, occurredAt: event.occurredAt,
    receivedAt, actorId: "digital-anne", subject: event.title,
    body: event.description ?? `${event.type} CRM-aktivitás.`,
    participants: [event.ownerEmail, event.contactEmail]
      .filter((value): value is string => Boolean(value)),
    labels: ["CRM", event.type.toUpperCase(), event.status.toUpperCase()],
    metadata: {
      provider: "CRM", eventType: crmEventType(event.type, event.status),
      connectorAccountId: context?.connectorAccountId,
      legalEntityId: context?.legalEntityId,
      activityId: event.activityId, projectId: event.projectId,
      leadId: event.leadId, dealId: event.dealId,
      ownerId: event.ownerId, ownerEmail: event.ownerEmail,
      contactEmail: event.contactEmail, dueAt: event.dueAt?.toISOString(),
      status: event.status, priority: event.priority,
    },
    status: "NORMALIZED",
    fingerprint: buildSourceFingerprint({
      organizationId, source: "WEBHOOK", externalId,
      subject: event.title, occurredAt: event.occurredAt,
    }),
  };
}

export function normalizeMarketingMetric(
  organizationId: string,
  event: MarketingMetricEvent,
  receivedAt: Date,
  context?: ConnectorEventContext,
): SourceEvent {
  const externalId = [
    event.provider.toLowerCase(),
    ...(context?.connectorAccountId ? [context.connectorAccountId] : []),
    event.accountId,
    event.campaignId,
    event.dateStart,
  ].join(":");
  return {
    id: sourceId(
      event.provider,
      context?.connectorAccountId,
      event.accountId,
      event.campaignId,
      event.dateStart,
    ),
    organizationId,
    source: "WEBHOOK",
    externalId,
    occurredAt: event.updatedAt,
    receivedAt,
    actorId: "digital-anne",
    subject: `${event.campaignName}: ${event.clicks} kattintás`,
    body:
      `${event.impressions} megjelenés; ${event.clicks} kattintás; ` +
      `${event.conversions} konverzió; ${event.spend} ${event.currency ?? ""}`.trim(),
    participants: [],
    labels: [event.provider, "MARKETING", "READ_ONLY_METRIC"],
    metadata: {
      provider: event.provider,
      eventType: "CAMPAIGN_METRICS_SNAPSHOT",
      connectorAccountId: context?.connectorAccountId,
      accountId: event.accountId,
      campaignId: event.campaignId,
      campaignName: event.campaignName,
      campaignStatus: event.campaignStatus,
      dateStart: event.dateStart,
      dateStop: event.dateStop,
      impressions: event.impressions,
      clicks: event.clicks,
      spend: event.spend,
      currency: event.currency,
      conversions: event.conversions,
      accessMode: "READ_ONLY",
    },
    status: "NORMALIZED",
    fingerprint: buildSourceFingerprint({
      organizationId,
      source: "WEBHOOK",
      externalId,
      subject: `${event.impressions}:${event.clicks}:${event.spend}:${event.conversions}`,
      occurredAt: event.updatedAt,
    }),
  };
}

function sourceId(
  provider: string,
  connectorAccountId: string | undefined,
  ...parts: Array<string | number>
) {
  const values = [
    "SRC",
    provider,
    ...(connectorAccountId ? [connectorAccountId] : []),
    ...parts,
  ];
  return values
    .map((value) => String(value).replace(/[^A-Za-z0-9._:-]+/g, "_"))
    .join("-");
}

function invoiceEventType(status: string): string {
  const value = status.toUpperCase();
  if (["PAID", "FULFILLED"].includes(value)) return "PAYMENT_RECEIVED";
  if (["OVERDUE", "EXPIRED"].includes(value)) return "PAYMENT_OVERDUE";
  if (["CANCELLED", "VOID"].includes(value)) return "INVOICE_CANCELLED";
  return "PAYMENT_DUE";
}
function crmEventType(type: string, status: string): string {
  if (type.toUpperCase().includes("LEAD")) return "LEAD_CREATED";
  if (type.toUpperCase().includes("CONTRACT")) return "CONTRACT_REVIEW_REQUESTED";
  if (status.toUpperCase() === "OVERDUE") return "CUSTOMER_DEADLINE";
  return "CRM_ACTIVITY_DUE";
}
