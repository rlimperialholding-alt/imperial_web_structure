import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createInterface } from "node:readline";
import { PrismaClient } from "@prisma/client";

const ORGANIZATION_ID = "imperial-holding";
const LEGAL_ENTITY_ID =
  "imperial-holding:imperial-holding-mernoki-es-tanacsado";
const CONNECTOR_ACCOUNT_ID =
  "billingo-imperial-holding-mernoki-es-tanacsado";
const BILLINGO_PROFILE_ID = "154-033";
const SOURCE_EXPORT = "Billingo incoming invoices filtered XLSX export";
const BATCH_SIZE = 250;

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function requiredText(row, name, lineNumber) {
  const value = row[name];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Missing ${name} on NDJSON line ${lineNumber}.`);
  }
  return value.trim();
}

function optionalText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function dateOnly(value, name, lineNumber, required = true) {
  if (!value && !required) return null;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`Invalid ${name} on NDJSON line ${lineNumber}.`);
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error(`Invalid ${name} on NDJSON line ${lineNumber}.`);
  }
  return parsed;
}

function amount(value, name, lineNumber) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid ${name} on NDJSON line ${lineNumber}.`);
  }
  return value;
}

function canonicalSourceRow(row) {
  return [
    optionalText(row.category),
    optionalText(row.paymentMethod),
    optionalText(row.invoiceNumber),
    row.issueDate ?? "",
    row.fulfillmentDate ?? "",
    row.dueDate ?? "",
    row.paymentDate ?? "",
    row.netAmount,
    row.vatAmount,
    row.grossAmount,
    optionalText(row.currency).toUpperCase(),
    optionalText(row.note),
    optionalText(row.partnerName),
    optionalText(row.taxNumber),
    optionalText(row.postalCode),
    optionalText(row.country),
    optionalText(row.city),
    optionalText(row.address),
    row.sourceRowNumber,
  ]
    .map((value) => Buffer.from(String(value), "utf8").toString("base64"))
    .join(".");
}

function toSourceEvent(row, lineNumber, importedAt) {
  const invoiceNumber = requiredText(row, "invoiceNumber", lineNumber);
  const partnerName = requiredText(row, "partnerName", lineNumber);
  const currency = requiredText(row, "currency", lineNumber).toUpperCase();
  const issueDate = dateOnly(row.issueDate, "issueDate", lineNumber);
  const fulfillmentDate = dateOnly(
    row.fulfillmentDate,
    "fulfillmentDate",
    lineNumber,
    false,
  );
  const dueDate = dateOnly(row.dueDate, "dueDate", lineNumber, false);
  const paymentDate = dateOnly(
    row.paymentDate,
    "paymentDate",
    lineNumber,
    false,
  );
  const netAmount = amount(row.netAmount, "netAmount", lineNumber);
  const vatAmount = amount(row.vatAmount, "vatAmount", lineNumber);
  const grossAmount = amount(row.grossAmount, "grossAmount", lineNumber);
  const expectedHash = sha256(canonicalSourceRow(row));
  if (row.rowHash !== expectedHash) {
    throw new Error(`Row hash mismatch on NDJSON line ${lineNumber}.`);
  }
  const externalId = `billingo:spending:${BILLINGO_PROFILE_ID}:${row.rowHash}`;
  const subject = `Bejövő számla ${invoiceNumber}: ${partnerName}`;
  const fingerprint = sha256(
    [
      ORGANIZATION_ID,
      "WEBHOOK",
      externalId,
      subject.trim().replace(/\s+/g, " ").toLowerCase(),
      issueDate.toISOString(),
    ].join("|"),
  );
  const paymentStatus = paymentDate ? "PAID" : "UNPAID";

  return {
    id: `SRC-BILLINGO-SPENDING-${row.rowHash}`,
    organizationId: ORGANIZATION_ID,
    legalEntityId: LEGAL_ENTITY_ID,
    source: "WEBHOOK",
    externalId,
    occurredAt: issueDate,
    receivedAt: importedAt,
    processedAt: importedAt,
    actorId: "digital-anne",
    subject,
    body: [
      `${partnerName} bejövő számlája.`,
      `Bruttó összeg: ${grossAmount} ${currency}.`,
      dueDate ? `Fizetési határidő: ${row.dueDate}.` : "",
      paymentDate ? `Kifizetve: ${row.paymentDate}.` : "Nincs kifizetve.",
    ]
      .filter(Boolean)
      .join(" "),
    participants: [partnerName],
    labels: [
      "BILLINGO",
      "FINANCIAL",
      "INCOMING_INVOICE",
      paymentStatus,
    ],
    metadata: {
      provider: "BILLINGO",
      eventType: "INCOMING_INVOICE",
      direction: "INCOMING",
      accessMode: "READ_ONLY",
      connectorAccountId: CONNECTOR_ACCOUNT_ID,
      legalEntityId: LEGAL_ENTITY_ID,
      profileId: BILLINGO_PROFILE_ID,
      category: optionalText(row.category),
      paymentMethod: optionalText(row.paymentMethod),
      invoiceNumber,
      issueDate: row.issueDate,
      fulfillmentDate: fulfillmentDate ? row.fulfillmentDate : null,
      dueDate: dueDate ? row.dueDate : null,
      paymentDate: paymentDate ? row.paymentDate : null,
      netAmount,
      vatAmount,
      grossAmount,
      currency,
      note: optionalText(row.note),
      partnerName,
      taxNumber: optionalText(row.taxNumber),
      postalCode: optionalText(row.postalCode),
      country: optionalText(row.country),
      city: optionalText(row.city),
      address: optionalText(row.address),
      sourceExport: SOURCE_EXPORT,
      sourceRowNumber: row.sourceRowNumber,
      sourceRowHash: row.rowHash,
    },
    status: "IGNORED",
    fingerprint,
    lastError: null,
  };
}

async function readEvents(path, importedAt) {
  await stat(path);
  const reader = createInterface({
    input: createReadStream(path, { encoding: "utf8" }),
    crlfDelay: Infinity,
  });
  const events = [];
  const hashes = new Set();
  let lineNumber = 0;
  for await (const line of reader) {
    lineNumber += 1;
    if (!line.trim()) continue;
    let row;
    try {
      row = JSON.parse(line);
    } catch {
      throw new Error(`Invalid JSON on NDJSON line ${lineNumber}.`);
    }
    const event = toSourceEvent(row, lineNumber, importedAt);
    if (hashes.has(row.rowHash)) {
      throw new Error(`Duplicate source row hash on NDJSON line ${lineNumber}.`);
    }
    hashes.add(row.rowHash);
    events.push(event);
  }
  if (events.length === 0) {
    throw new Error("The import file contains no invoice rows.");
  }
  return events;
}

function summarize(events) {
  const currencyTotals = {};
  let paidRows = 0;
  let minIssueDate = null;
  let maxIssueDate = null;
  for (const event of events) {
    const metadata = event.metadata;
    const current = currencyTotals[metadata.currency] ?? {
      count: 0,
      gross: 0,
    };
    current.count += 1;
    current.gross += metadata.grossAmount;
    currencyTotals[metadata.currency] = current;
    if (metadata.paymentDate) paidRows += 1;
    if (!minIssueDate || metadata.issueDate < minIssueDate) {
      minIssueDate = metadata.issueDate;
    }
    if (!maxIssueDate || metadata.issueDate > maxIssueDate) {
      maxIssueDate = metadata.issueDate;
    }
  }
  return {
    inputRows: events.length,
    paidRows,
    unpaidRows: events.length - paidRows,
    minIssueDate,
    maxIssueDate,
    currencyTotals,
  };
}

async function validateTarget(prisma) {
  const [entity, connector] = await Promise.all([
    prisma.legalEntity.findUnique({ where: { id: LEGAL_ENTITY_ID } }),
    prisma.connectorAccount.findUnique({
      where: { id: CONNECTOR_ACCOUNT_ID },
    }),
  ]);
  if (!entity || entity.organizationId !== ORGANIZATION_ID) {
    throw new Error("Target legal entity is missing or belongs to another organization.");
  }
  if (
    !connector ||
    connector.organizationId !== ORGANIZATION_ID ||
    connector.legalEntityId !== LEGAL_ENTITY_ID ||
    connector.kind !== "BILLINGO" ||
    connector.status !== "ACTIVE"
  ) {
    throw new Error("The active Billingo connector does not match the target legal entity.");
  }
}

async function main() {
  const inputPath = process.argv.find((arg) => !arg.startsWith("--") && arg !== process.argv[0] && arg !== process.argv[1]);
  const dryRun = process.argv.includes("--dry-run");
  if (!inputPath) {
    throw new Error(
      "Usage: node scripts/import-billingo-spending.mjs <file.ndjson> [--dry-run]",
    );
  }
  const importedAt = new Date();
  const events = await readEvents(inputPath, importedAt);
  const summary = summarize(events);
  if (dryRun) {
    console.log(JSON.stringify({ ...summary, dryRun: true }, null, 2));
    return;
  }

  const prisma = new PrismaClient();
  let createdRows = 0;
  try {
    await validateTarget(prisma);
    for (let start = 0; start < events.length; start += BATCH_SIZE) {
      const batch = events.slice(start, start + BATCH_SIZE);
      const result = await prisma.sourceEvent.createMany({
        data: batch,
        skipDuplicates: true,
      });
      createdRows += result.count;
    }
  } finally {
    await prisma.$disconnect();
  }
  console.log(
    JSON.stringify(
      {
        ...summary,
        createdRows,
        skippedRows: events.length - createdRows,
        dryRun: false,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
