import { and, asc, eq, or } from "drizzle-orm";
import { getDb } from "@/db";
import { customerImports, leads } from "@/db/schema";

const MAX_CUSTOMERS_PER_BATCH = 250;
const identifierPattern = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/;
const allowedSourceHosts = new Set([
  "drive.google.com",
  "docs.google.com",
  "mail.google.com",
]);

type SourceKind = "contract_customer" | "web_form_lead";

type CustomerInput = {
  externalId: string;
  sourceKind: SourceKind;
  name: string;
  title: string;
  email: string;
  phone: string;
  location: string;
  projectType: string;
  sourceUrl: string;
  sourceDate: string;
};

type CustomerImportPayload = {
  workspaceId: string;
  sourceSystem: string;
  customers: CustomerInput[];
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

function optionalText(value: unknown, maxLength: number, fallback: string) {
  const normalized = String(value ?? "").trim();
  return normalized ? normalized.slice(0, maxLength) : fallback;
}

function sourceUrl(value: unknown) {
  const normalized = requiredText(value, "sourceUrl", 600);
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Response("sourceUrl is invalid.", { status: 400 });
  }
  if (parsed.protocol !== "https:" || !allowedSourceHosts.has(parsed.hostname)) {
    throw new Response("sourceUrl must be an approved Google source.", {
      status: 400,
    });
  }
  return parsed.toString();
}

function sourceDate(value: unknown) {
  const normalized = requiredText(value, "sourceDate", 40);
  if (Number.isNaN(Date.parse(normalized))) {
    throw new Response("sourceDate is invalid.", { status: 400 });
  }
  return new Date(normalized).toISOString();
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

async function payloadHash(customer: CustomerInput) {
  const bytes = new TextEncoder().encode(canonicalJson(customer));
  return toHex(await crypto.subtle.digest("SHA-256", bytes));
}

export function parseCustomerImportPayload(value: unknown): CustomerImportPayload {
  const payload = value && typeof value === "object"
    ? value as Record<string, unknown>
    : {};
  const rawCustomers = Array.isArray(payload.customers) ? payload.customers : [];
  if (!rawCustomers.length || rawCustomers.length > MAX_CUSTOMERS_PER_BATCH) {
    throw new Response("A customer import batch must contain 1-250 records.", {
      status: 400,
    });
  }
  const customers = rawCustomers.map((value, index) => {
    const item = value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
    const sourceKind = String(item.sourceKind ?? "") as SourceKind;
    if (!["contract_customer", "web_form_lead"].includes(sourceKind)) {
      throw new Response(`customers[${index}].sourceKind is invalid.`, {
        status: 400,
      });
    }
    return {
      externalId: requiredIdentifier(
        item.externalId,
        `customers[${index}].externalId`,
      ),
      sourceKind,
      name: requiredText(item.name, `customers[${index}].name`, 200),
      title: optionalText(
        item.title,
        240,
        sourceKind === "contract_customer"
          ? "Szerződéses ügyfél"
          : "Webes érdeklődő",
      ),
      email: optionalText(item.email, 320, "—").toLowerCase(),
      phone: optionalText(item.phone, 80, "—"),
      location: optionalText(item.location, 240, "Nincs megadva"),
      projectType: optionalText(item.projectType, 160, "Egyeztetendő"),
      sourceUrl: sourceUrl(item.sourceUrl),
      sourceDate: sourceDate(item.sourceDate),
    };
  });
  if (new Set(customers.map((item) => item.externalId)).size !== customers.length) {
    throw new Response("externalId values must be unique within the pilot.", {
      status: 400,
    });
  }
  return {
    workspaceId: requiredIdentifier(payload.workspaceId, "workspaceId"),
    sourceSystem: requiredIdentifier(payload.sourceSystem, "sourceSystem"),
    customers,
  };
}

export async function importCustomers(request: Request) {
  let rawPayload: unknown;
  try {
    rawPayload = await request.json();
  } catch {
    throw new Response("The request body must be valid JSON.", { status: 400 });
  }
  const payload = parseCustomerImportPayload(rawPayload);
  const db = await getDb();
  const imported = [];
  let newlyStored = 0;

  for (const customer of payload.customers) {
    const digest = await payloadHash(customer);
    const [existing] = await db.select().from(customerImports).where(and(
      eq(customerImports.workspaceId, payload.workspaceId),
      eq(customerImports.sourceSystem, payload.sourceSystem),
      eq(customerImports.externalId, customer.externalId),
    )).limit(1);
    if (existing) {
      if (existing.payloadSha256 !== digest) {
        throw new Response(
          `${customer.externalId} already exists with different data.`,
          { status: 409 },
        );
      }
      imported.push({
        externalId: existing.externalId,
        leadId: existing.leadId,
        sourceKind: existing.sourceKind,
        importedAt: existing.importedAt,
        duplicate: true,
      });
      continue;
    }

    const now = new Date().toISOString();
    const isContract = customer.sourceKind === "contract_customer";
    const contactMatches = [];
    if (customer.email !== "â€”") {
      contactMatches.push(eq(leads.email, customer.email));
    }
    if (customer.phone !== "â€”") {
      contactMatches.push(eq(leads.phone, customer.phone));
    }
    const [matchedLead] = contactMatches.length
      ? await db.select({ id: leads.id }).from(leads)
        .where(or(...contactMatches))
        .orderBy(asc(leads.id))
        .limit(1)
      : [];
    const [createdLead] = matchedLead
      ? []
      : await db.insert(leads).values({
      name: customer.name,
      title: customer.title,
      brand: "Imperial",
      brandCode: "IH",
      location: customer.location,
      email: customer.email,
      phone: customer.phone,
      source: isContract
        ? "Google Drive – aláírt szerződés"
        : "Gmail – webes űrlap",
      owner: "Migrációs pilot",
      ownerInitials: "MP",
      stage: isContract ? "contract" : "new",
      value: 0,
      probability: isContract ? 100 : 10,
      score: isContract ? 100 : 45,
      quality: isContract ? 90 : 60,
      temperature: isContract ? "warm" : "cold",
      health: isContract ? "green" : "yellow",
      nextAction: isContract
        ? "Szerződés és projektkapcsolat ellenőrzése"
        : "Első kapcsolatfelvétel",
      nextDate: "Manuális ellenőrzés szükséges",
      projectType: customer.projectType,
      technology: "Egyeztetendő",
      plot: false,
      financing: false,
      notes: `Forrás: ${customer.sourceUrl}`,
      createdAt: now,
      updatedAt: now,
      }).returning({ id: leads.id });
    const lead = matchedLead ?? createdLead;

    const [source] = await db.insert(customerImports).values({
      workspaceId: payload.workspaceId,
      sourceSystem: payload.sourceSystem,
      externalId: customer.externalId,
      sourceKind: customer.sourceKind,
      leadId: lead.id,
      sourceUrl: customer.sourceUrl,
      sourceDate: customer.sourceDate,
      payloadSha256: digest,
      metadataJson: canonicalJson(customer),
      importedAt: now,
    }).returning();
    newlyStored += 1;
    imported.push({
      externalId: source.externalId,
      leadId: source.leadId,
      sourceKind: source.sourceKind,
      importedAt: source.importedAt,
      duplicate: false,
    });
  }

  return {
    workspaceId: payload.workspaceId,
    sourceSystem: payload.sourceSystem,
    requestedCount: payload.customers.length,
    storedCount: imported.length,
    newlyStored,
    duplicateCount: imported.length - newlyStored,
    customers: imported,
  };
}

export async function listImportedCustomers(workspaceId: string) {
  const normalizedWorkspaceId = requiredIdentifier(workspaceId, "workspaceId");
  const db = await getDb();
  const rows = await db.select({
    id: customerImports.id,
    externalId: customerImports.externalId,
    sourceKind: customerImports.sourceKind,
    leadId: customerImports.leadId,
    sourceUrl: customerImports.sourceUrl,
    sourceDate: customerImports.sourceDate,
    importedAt: customerImports.importedAt,
    name: leads.name,
    email: leads.email,
    phone: leads.phone,
    stage: leads.stage,
    projectType: leads.projectType,
  }).from(customerImports).innerJoin(
    leads,
    eq(customerImports.leadId, leads.id),
  ).where(eq(customerImports.workspaceId, normalizedWorkspaceId))
    .orderBy(asc(customerImports.id));
  return { workspaceId: normalizedWorkspaceId, customers: rows };
}
