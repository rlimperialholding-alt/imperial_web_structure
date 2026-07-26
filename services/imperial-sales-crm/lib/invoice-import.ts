import { and, asc, eq } from "drizzle-orm";
import { getDb } from "@/db";
import {
  customerImports,
  financeInvoiceImports,
  leads,
  projects,
} from "@/db/schema";

const MAX_INVOICES_PER_PILOT = 10;
const identifierPattern = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/;
const sha256Pattern = /^[a-f0-9]{64}$/;

type InvoiceType = "invoice" | "storno";

type InvoiceInput = {
  externalId: string;
  invoiceNumber: string;
  invoiceType: InvoiceType;
  sellerName: string;
  buyerName: string;
  issueDate: string;
  fulfillmentDate: string;
  dueDate: string;
  paymentMethod: string;
  currency: "HUF";
  netAmount: number;
  taxAmount: number;
  grossAmount: number;
  description: string;
  referencedInvoiceNumber: string | null;
  customerSourceSystem: string;
  customerExternalId: string;
  sourceUrl: string;
  sourceFileName: string;
  sourceSha256: string;
};

type InvoiceImportPayload = {
  workspaceId: string;
  sourceSystem: string;
  invoices: InvoiceInput[];
};

function requiredIdentifier(value: unknown, field: string) {
  const normalized = String(value ?? "").trim();
  if (!identifierPattern.test(normalized)) {
    throw new Response(`${field} is invalid.`, { status: 400 });
  }
  return normalized;
}

function requiredText(value: unknown, field: string, maxLength: number) {
  const normalized = String(value ?? "").trim();
  if (!normalized || normalized.length > maxLength) {
    throw new Response(`${field} is invalid.`, { status: 400 });
  }
  return normalized;
}

function optionalText(value: unknown, maxLength: number) {
  const normalized = String(value ?? "").trim();
  return normalized ? normalized.slice(0, maxLength) : null;
}

function invoiceDate(value: unknown, field: string) {
  const normalized = requiredText(value, field, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalized) ||
      Number.isNaN(Date.parse(`${normalized}T00:00:00Z`))) {
    throw new Response(`${field} is invalid.`, { status: 400 });
  }
  return normalized;
}

function integerAmount(value: unknown, field: string) {
  const amount = Number(value);
  if (!Number.isSafeInteger(amount) || Math.abs(amount) > 10_000_000_000) {
    throw new Response(`${field} is invalid.`, { status: 400 });
  }
  return amount;
}

function driveSourceUrl(value: unknown) {
  const normalized = requiredText(value, "sourceUrl", 600);
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Response("sourceUrl is invalid.", { status: 400 });
  }
  if (parsed.protocol !== "https:" || parsed.hostname !== "drive.google.com") {
    throw new Response("sourceUrl must be a Google Drive source.", {
      status: 400,
    });
  }
  return parsed.toString();
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function toHex(buffer: ArrayBuffer) {
  return Array.from(
    new Uint8Array(buffer),
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}

async function payloadHash(invoice: InvoiceInput) {
  const bytes = new TextEncoder().encode(canonicalJson(invoice));
  return toHex(await crypto.subtle.digest("SHA-256", bytes));
}

function normalizedCustomerName(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/^dr[.\s]+/, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function parseInvoiceImportPayload(value: unknown): InvoiceImportPayload {
  const payload = value && typeof value === "object"
    ? value as Record<string, unknown>
    : {};
  const rawInvoices = Array.isArray(payload.invoices) ? payload.invoices : [];
  if (!rawInvoices.length || rawInvoices.length > MAX_INVOICES_PER_PILOT) {
    throw new Response("An invoice pilot must contain 1-10 records.", {
      status: 400,
    });
  }

  const invoices = rawInvoices.map((value, index) => {
    const item = value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
    const invoiceType = String(item.invoiceType ?? "") as InvoiceType;
    if (!["invoice", "storno"].includes(invoiceType)) {
      throw new Response(`invoices[${index}].invoiceType is invalid.`, {
        status: 400,
      });
    }
    const currency = requiredText(item.currency, "currency", 3);
    if (currency !== "HUF") {
      throw new Response("The invoice pilot currently accepts HUF only.", {
        status: 400,
      });
    }
    const netAmount = integerAmount(item.netAmount, "netAmount");
    const taxAmount = integerAmount(item.taxAmount, "taxAmount");
    const grossAmount = integerAmount(item.grossAmount, "grossAmount");
    if (netAmount + taxAmount !== grossAmount) {
      throw new Response("netAmount + taxAmount must equal grossAmount.", {
        status: 400,
      });
    }
    if ((invoiceType === "invoice" && grossAmount <= 0) ||
        (invoiceType === "storno" && grossAmount >= 0)) {
      throw new Response("invoiceType does not match the amount sign.", {
        status: 400,
      });
    }
    const referencedInvoiceNumber = optionalText(
      item.referencedInvoiceNumber,
      128,
    );
    if (invoiceType === "storno" && !referencedInvoiceNumber) {
      throw new Response("A storno invoice needs referencedInvoiceNumber.", {
        status: 400,
      });
    }
    const sourceFileName = requiredText(
      item.sourceFileName,
      "sourceFileName",
      260,
    );
    if (!sourceFileName.toLowerCase().endsWith(".pdf")) {
      throw new Response("sourceFileName must be a PDF.", { status: 400 });
    }
    const sourceSha256 = requiredText(
      item.sourceSha256,
      "sourceSha256",
      64,
    ).toLowerCase();
    if (!sha256Pattern.test(sourceSha256)) {
      throw new Response("sourceSha256 is invalid.", { status: 400 });
    }
    return {
      externalId: requiredIdentifier(item.externalId, "externalId"),
      invoiceNumber: requiredIdentifier(item.invoiceNumber, "invoiceNumber"),
      invoiceType,
      sellerName: requiredText(item.sellerName, "sellerName", 240),
      buyerName: requiredText(item.buyerName, "buyerName", 240),
      issueDate: invoiceDate(item.issueDate, "issueDate"),
      fulfillmentDate: invoiceDate(item.fulfillmentDate, "fulfillmentDate"),
      dueDate: invoiceDate(item.dueDate, "dueDate"),
      paymentMethod: requiredText(item.paymentMethod, "paymentMethod", 80),
      currency: "HUF" as const,
      netAmount,
      taxAmount,
      grossAmount,
      description: requiredText(item.description, "description", 1000),
      referencedInvoiceNumber,
      customerSourceSystem: requiredIdentifier(
        item.customerSourceSystem,
        "customerSourceSystem",
      ),
      customerExternalId: requiredIdentifier(
        item.customerExternalId,
        "customerExternalId",
      ),
      sourceUrl: driveSourceUrl(item.sourceUrl),
      sourceFileName,
      sourceSha256,
    };
  });

  if (new Set(invoices.map((item) => item.externalId)).size !== invoices.length ||
      new Set(invoices.map((item) => item.invoiceNumber)).size !== invoices.length) {
    throw new Response(
      "Invoice external IDs and invoice numbers must be unique within the pilot.",
      { status: 400 },
    );
  }
  return {
    workspaceId: requiredIdentifier(payload.workspaceId, "workspaceId"),
    sourceSystem: requiredIdentifier(payload.sourceSystem, "sourceSystem"),
    invoices,
  };
}

export async function importInvoices(request: Request) {
  let rawPayload: unknown;
  try {
    rawPayload = await request.json();
  } catch {
    throw new Response("The request body must be valid JSON.", { status: 400 });
  }
  const payload = parseInvoiceImportPayload(rawPayload);
  const db = await getDb();
  const imported = [];
  let newlyStored = 0;

  for (const invoice of payload.invoices) {
    const digest = await payloadHash(invoice);
    const [existing] = await db.select().from(financeInvoiceImports).where(and(
      eq(financeInvoiceImports.workspaceId, payload.workspaceId),
      eq(financeInvoiceImports.sourceSystem, payload.sourceSystem),
      eq(financeInvoiceImports.externalId, invoice.externalId),
    )).limit(1);
    if (existing) {
      if (existing.payloadSha256 !== digest) {
        throw new Response(
          `${invoice.externalId} already exists with different data.`,
          { status: 409 },
        );
      }
      imported.push({
        externalId: existing.externalId,
        invoiceNumber: existing.invoiceNumber,
        customerMatchStatus: existing.customerMatchStatus,
        projectMatchStatus: existing.projectMatchStatus,
        duplicate: true,
      });
      continue;
    }
    const [numberCollision] = await db.select({
      externalId: financeInvoiceImports.externalId,
    }).from(financeInvoiceImports).where(and(
      eq(financeInvoiceImports.workspaceId, payload.workspaceId),
      eq(financeInvoiceImports.sourceSystem, payload.sourceSystem),
      eq(financeInvoiceImports.invoiceNumber, invoice.invoiceNumber),
    )).limit(1);
    if (numberCollision) {
      throw new Response(
        `${invoice.invoiceNumber} is already assigned to another source file.`,
        { status: 409 },
      );
    }

    const [customer] = await db.select({
      customerImportId: customerImports.id,
      leadId: customerImports.leadId,
      customerName: leads.name,
    }).from(customerImports).innerJoin(
      leads,
      eq(customerImports.leadId, leads.id),
    ).where(and(
      eq(customerImports.workspaceId, payload.workspaceId),
      eq(customerImports.sourceSystem, invoice.customerSourceSystem),
      eq(customerImports.externalId, invoice.customerExternalId),
    )).limit(1);
    if (!customer) {
      throw new Response(
        `${invoice.invoiceNumber} has no verified imported CRM customer.`,
        { status: 422 },
      );
    }
    if (normalizedCustomerName(customer.customerName) !==
        normalizedCustomerName(invoice.buyerName)) {
      throw new Response(
        `${invoice.invoiceNumber} buyer does not match the CRM customer.`,
        { status: 409 },
      );
    }

    const projectCandidates = await db.select({
      id: projects.id,
    }).from(projects).where(
      eq(projects.customerName, customer.customerName),
    ).limit(2);
    const matchedProject = projectCandidates.length === 1
      ? projectCandidates[0]
      : null;
    const projectMatchStatus = matchedProject
      ? "matched"
      : projectCandidates.length > 1
        ? "review"
        : "unmatched";
    const now = new Date().toISOString();
    const [stored] = await db.insert(financeInvoiceImports).values({
      workspaceId: payload.workspaceId,
      sourceSystem: payload.sourceSystem,
      externalId: invoice.externalId,
      sourceUrl: invoice.sourceUrl,
      sourceFileName: invoice.sourceFileName,
      sourceSha256: invoice.sourceSha256,
      invoiceNumber: invoice.invoiceNumber,
      invoiceType: invoice.invoiceType,
      sellerName: invoice.sellerName,
      buyerName: invoice.buyerName,
      issueDate: invoice.issueDate,
      fulfillmentDate: invoice.fulfillmentDate,
      dueDate: invoice.dueDate,
      paymentMethod: invoice.paymentMethod,
      currency: invoice.currency,
      netAmount: invoice.netAmount,
      taxAmount: invoice.taxAmount,
      grossAmount: invoice.grossAmount,
      description: invoice.description,
      referencedInvoiceNumber: invoice.referencedInvoiceNumber,
      customerImportId: customer.customerImportId,
      leadId: customer.leadId,
      projectId: matchedProject?.id ?? null,
      customerMatchStatus: "matched",
      projectMatchStatus,
      matchConfidence: 100,
      payloadSha256: digest,
      metadataJson: canonicalJson(invoice),
      importedAt: now,
    }).returning();
    newlyStored += 1;
    imported.push({
      externalId: stored.externalId,
      invoiceNumber: stored.invoiceNumber,
      customerMatchStatus: stored.customerMatchStatus,
      projectMatchStatus: stored.projectMatchStatus,
      duplicate: false,
    });
  }

  return {
    workspaceId: payload.workspaceId,
    sourceSystem: payload.sourceSystem,
    requestedCount: payload.invoices.length,
    storedCount: imported.length,
    newlyStored,
    duplicateCount: imported.length - newlyStored,
    customerMatchedCount: imported.filter(
      (item) => item.customerMatchStatus === "matched",
    ).length,
    projectMatchedCount: imported.filter(
      (item) => item.projectMatchStatus === "matched",
    ).length,
    invoices: imported,
  };
}

export async function listFinanceInvoices(workspaceId?: string) {
  const db = await getDb();
  const select = db.select({
    id: financeInvoiceImports.id,
    workspaceId: financeInvoiceImports.workspaceId,
    externalId: financeInvoiceImports.externalId,
    invoiceNumber: financeInvoiceImports.invoiceNumber,
    invoiceType: financeInvoiceImports.invoiceType,
    buyerName: financeInvoiceImports.buyerName,
    sellerName: financeInvoiceImports.sellerName,
    issueDate: financeInvoiceImports.issueDate,
    fulfillmentDate: financeInvoiceImports.fulfillmentDate,
    dueDate: financeInvoiceImports.dueDate,
    paymentMethod: financeInvoiceImports.paymentMethod,
    currency: financeInvoiceImports.currency,
    netAmount: financeInvoiceImports.netAmount,
    taxAmount: financeInvoiceImports.taxAmount,
    grossAmount: financeInvoiceImports.grossAmount,
    description: financeInvoiceImports.description,
    referencedInvoiceNumber: financeInvoiceImports.referencedInvoiceNumber,
    sourceUrl: financeInvoiceImports.sourceUrl,
    sourceFileName: financeInvoiceImports.sourceFileName,
    customerMatchStatus: financeInvoiceImports.customerMatchStatus,
    projectMatchStatus: financeInvoiceImports.projectMatchStatus,
    matchConfidence: financeInvoiceImports.matchConfidence,
    importedAt: financeInvoiceImports.importedAt,
    leadId: financeInvoiceImports.leadId,
    projectId: financeInvoiceImports.projectId,
    crmCustomerName: leads.name,
    projectTitle: projects.title,
  }).from(financeInvoiceImports).leftJoin(
    leads,
    eq(financeInvoiceImports.leadId, leads.id),
  ).leftJoin(
    projects,
    eq(financeInvoiceImports.projectId, projects.id),
  );
  if (workspaceId) {
    const normalized = requiredIdentifier(workspaceId, "workspaceId");
    return select.where(
      eq(financeInvoiceImports.workspaceId, normalized),
    ).orderBy(asc(financeInvoiceImports.id));
  }
  return select.orderBy(asc(financeInvoiceImports.id));
}
