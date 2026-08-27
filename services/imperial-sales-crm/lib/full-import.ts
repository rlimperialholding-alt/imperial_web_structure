import { and, asc, eq, sql } from "drizzle-orm";
import { getDb } from "@/db";
import {
  businessPartnerSources,
  businessPartners,
  businessProjects,
  customerImports,
  importReviewItems,
  sourceRecords,
} from "@/db/schema";

const MAX_ITEMS_PER_COLLECTION = 250;
const identifierPattern = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,255}$/;
const allowedSourceHosts = new Set([
  "drive.google.com",
  "docs.google.com",
  "mail.google.com",
]);

type SourceKind =
  | "drive_file"
  | "drive_folder"
  | "gmail_message"
  | "spreadsheet_row";
type RecordType =
  | "customer_source"
  | "lead_source"
  | "project"
  | "contract"
  | "project_document"
  | "invoice_source"
  | "partner_source"
  | "restricted_source"
  | "other";
type ReviewStatus = "verified" | "review" | "excluded";
type PartnerType =
  | "subcontractor"
  | "supplier"
  | "designer"
  | "architect"
  | "b2b_partner";
type PartnerStatus = "verified" | "prospect" | "review" | "excluded";
type ProjectStatus =
  | "active"
  | "planning"
  | "on_hold"
  | "completed"
  | "archived"
  | "review";

type SourceRecordInput = {
  externalId: string;
  sourceKind: SourceKind;
  recordType: RecordType;
  title: string;
  sourceUrl: string;
  mimeType: string | null;
  byteSize: number | null;
  parentExternalId: string | null;
  sourceVersion: string;
  reviewStatus: ReviewStatus;
  metadata: Record<string, unknown>;
};

type PartnerInput = {
  sourceExternalId: string;
  partnerType: PartnerType;
  name: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  specialties: string | null;
  recordStatus: PartnerStatus;
  matchConfidence: number;
  metadata: Record<string, unknown>;
};

type ProjectInput = {
  sourceExternalId: string;
  externalKey: string;
  title: string;
  location: string | null;
  projectType: string | null;
  projectStatus: ProjectStatus;
  customerSourceSystem: string | null;
  customerExternalId: string | null;
  metadata: Record<string, unknown>;
};

type ReviewInput = {
  sourceExternalId: string;
  entityType: string;
  reasonCode: string;
  summary: string;
};

type FullImportPayload = {
  workspaceId: string;
  sourceSystem: string;
  records: SourceRecordInput[];
  partners: PartnerInput[];
  projects: ProjectInput[];
  reviews: ReviewInput[];
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

function enumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  field: string,
): T {
  const normalized = String(value ?? "") as T;
  if (!allowed.includes(normalized)) {
    throw new Response(`${field} is invalid.`, { status: 400 });
  }
  return normalized;
}

function sourceUrl(value: unknown) {
  const normalized = requiredText(value, "sourceUrl", 800);
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

function metadata(value: unknown, field: string) {
  const parsed = value === undefined ? {} : value;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Response(`${field} is invalid.`, { status: 400 });
  }
  const serialized = canonicalJson(parsed);
  if (serialized.length > 32_000) {
    throw new Response(`${field} is too large.`, { status: 413 });
  }
  return parsed as Record<string, unknown>;
}

function boundedArray(value: unknown, field: string) {
  const items = value === undefined ? [] : value;
  if (!Array.isArray(items) || items.length > MAX_ITEMS_PER_COLLECTION) {
    throw new Response(`${field} must contain at most 250 records.`, {
      status: 400,
    });
  }
  return items;
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

async function sha256(value: unknown) {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  return toHex(await crypto.subtle.digest("SHA-256", bytes));
}

function contactConfidence(value: unknown) {
  const score = Number(value);
  if (!Number.isInteger(score) || score < 0 || score > 100) {
    throw new Response("matchConfidence must be an integer from 0 to 100.", {
      status: 400,
    });
  }
  return score;
}

function byteSize(value: unknown) {
  if (value === undefined || value === null || value === "") return null;
  const size = Number(value);
  if (!Number.isSafeInteger(size) || size < 0) {
    throw new Response("byteSize is invalid.", { status: 400 });
  }
  return size;
}

export function parseFullImportPayload(value: unknown): FullImportPayload {
  const payload = value && typeof value === "object"
    ? value as Record<string, unknown>
    : {};
  const records = boundedArray(payload.records, "records").map((value, index) => {
    const item = value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
    return {
      externalId: requiredIdentifier(
        item.externalId,
        `records[${index}].externalId`,
      ),
      sourceKind: enumValue(
        item.sourceKind,
        ["drive_file", "drive_folder", "gmail_message", "spreadsheet_row"],
        `records[${index}].sourceKind`,
      ),
      recordType: enumValue(
        item.recordType,
        [
          "customer_source",
          "lead_source",
          "project",
          "contract",
          "project_document",
          "invoice_source",
          "partner_source",
          "restricted_source",
          "other",
        ],
        `records[${index}].recordType`,
      ),
      title: requiredText(item.title, `records[${index}].title`, 1000),
      sourceUrl: sourceUrl(item.sourceUrl),
      mimeType: optionalText(item.mimeType, 200),
      byteSize: byteSize(item.byteSize),
      parentExternalId: item.parentExternalId
        ? requiredIdentifier(
          item.parentExternalId,
          `records[${index}].parentExternalId`,
        )
        : null,
      sourceVersion: requiredText(
        item.sourceVersion,
        `records[${index}].sourceVersion`,
        160,
      ),
      reviewStatus: enumValue(
        item.reviewStatus,
        ["verified", "review", "excluded"],
        `records[${index}].reviewStatus`,
      ),
      metadata: metadata(item.metadata, `records[${index}].metadata`),
    };
  });
  if (new Set(records.map((item) => item.externalId)).size !== records.length) {
    throw new Response("record external IDs must be unique within the batch.", {
      status: 400,
    });
  }

  const partners = boundedArray(payload.partners, "partners").map((value, index) => {
    const item = value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
    return {
      sourceExternalId: requiredIdentifier(
        item.sourceExternalId,
        `partners[${index}].sourceExternalId`,
      ),
      partnerType: enumValue(
        item.partnerType,
        ["subcontractor", "supplier", "designer", "architect", "b2b_partner"],
        `partners[${index}].partnerType`,
      ),
      name: requiredText(item.name, `partners[${index}].name`, 1000),
      email: optionalText(item.email, 320)?.toLowerCase() ?? null,
      phone: optionalText(item.phone, 100),
      location: optionalText(item.location, 320),
      specialties: optionalText(item.specialties, 1000),
      recordStatus: enumValue(
        item.recordStatus,
        ["verified", "prospect", "review", "excluded"],
        `partners[${index}].recordStatus`,
      ),
      matchConfidence: contactConfidence(item.matchConfidence),
      metadata: metadata(item.metadata, `partners[${index}].metadata`),
    };
  });

  const projects = boundedArray(payload.projects, "projects").map((value, index) => {
    const item = value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
    const customerSourceSystem = optionalText(item.customerSourceSystem, 255);
    const customerExternalId = optionalText(item.customerExternalId, 255);
    if ((customerSourceSystem && !customerExternalId) ||
        (!customerSourceSystem && customerExternalId)) {
      throw new Response(
        `projects[${index}] needs both customer source identifiers.`,
        { status: 400 },
      );
    }
    return {
      sourceExternalId: requiredIdentifier(
        item.sourceExternalId,
        `projects[${index}].sourceExternalId`,
      ),
      externalKey: requiredIdentifier(
        item.externalKey,
        `projects[${index}].externalKey`,
      ),
      title: requiredText(item.title, `projects[${index}].title`, 320),
      location: optionalText(item.location, 320),
      projectType: optionalText(item.projectType, 200),
      projectStatus: enumValue(
        item.projectStatus,
        ["active", "planning", "on_hold", "completed", "archived", "review"],
        `projects[${index}].projectStatus`,
      ),
      customerSourceSystem,
      customerExternalId,
      metadata: metadata(item.metadata, `projects[${index}].metadata`),
    };
  });

  const reviews = boundedArray(payload.reviews, "reviews").map((value, index) => {
    const item = value && typeof value === "object"
      ? value as Record<string, unknown>
      : {};
    return {
      sourceExternalId: requiredIdentifier(
        item.sourceExternalId,
        `reviews[${index}].sourceExternalId`,
      ),
      entityType: requiredIdentifier(
        item.entityType,
        `reviews[${index}].entityType`,
      ),
      reasonCode: requiredIdentifier(
        item.reasonCode,
        `reviews[${index}].reasonCode`,
      ),
      summary: requiredText(item.summary, `reviews[${index}].summary`, 500),
    };
  });

  if (!records.length && !partners.length && !projects.length && !reviews.length) {
    throw new Response("The import batch is empty.", { status: 400 });
  }
  return {
    workspaceId: requiredIdentifier(payload.workspaceId, "workspaceId"),
    sourceSystem: requiredIdentifier(payload.sourceSystem, "sourceSystem"),
    records,
    partners,
    projects,
    reviews,
  };
}

async function sourceRecordByExternalId(
  workspaceId: string,
  sourceSystem: string,
  externalId: string,
) {
  const db = await getDb();
  const [record] = await db.select().from(sourceRecords).where(and(
    eq(sourceRecords.workspaceId, workspaceId),
    eq(sourceRecords.sourceSystem, sourceSystem),
    eq(sourceRecords.externalId, externalId),
  )).limit(1);
  return record ?? null;
}

function normalizedIdentityPart(value: string | null) {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9@.+]+/g, " ")
    .trim();
}

async function partnerIdentity(partner: PartnerInput) {
  const email = normalizedIdentityPart(partner.email);
  const phone = (partner.phone ?? "").replace(/\D/g, "");
  const raw = email
    ? `email:${email}`
    : phone.length >= 7
      ? `phone:${phone}`
      : `name:${normalizedIdentityPart(partner.name)}|${normalizedIdentityPart(partner.location)}`;
  return sha256(raw);
}

export async function importFullBatch(request: Request) {
  let rawPayload: unknown;
  try {
    rawPayload = await request.json();
  } catch {
    throw new Response("The request body must be valid JSON.", { status: 400 });
  }
  const payload = parseFullImportPayload(rawPayload);
  const db = await getDb();
  const now = new Date().toISOString();
  let newRecords = 0;
  let updatedRecords = 0;
  let newPartners = 0;
  let newProjects = 0;
  let newReviews = 0;

  for (const record of payload.records) {
    const digest = await sha256(record);
    const existing = await sourceRecordByExternalId(
      payload.workspaceId,
      payload.sourceSystem,
      record.externalId,
    );
    if (!existing) {
      await db.insert(sourceRecords).values({
        workspaceId: payload.workspaceId,
        sourceSystem: payload.sourceSystem,
        externalId: record.externalId,
        sourceKind: record.sourceKind,
        recordType: record.recordType,
        title: record.title,
        sourceUrl: record.sourceUrl,
        mimeType: record.mimeType,
        byteSize: record.byteSize,
        parentExternalId: record.parentExternalId,
        sourceVersion: record.sourceVersion,
        storageMode: "link",
        reviewStatus: record.reviewStatus,
        payloadSha256: digest,
        metadataJson: canonicalJson(record.metadata),
        firstSeenAt: now,
        lastSeenAt: now,
        updatedAt: now,
      });
      newRecords += 1;
      continue;
    }
    if (existing.sourceVersion === record.sourceVersion &&
        existing.payloadSha256 !== digest) {
      throw new Response(
        `${record.externalId} changed without a new source version.`,
        { status: 409 },
      );
    }
    await db.update(sourceRecords).set({
      sourceKind: record.sourceKind,
      recordType: record.recordType,
      title: record.title,
      sourceUrl: record.sourceUrl,
      mimeType: record.mimeType,
      byteSize: record.byteSize,
      parentExternalId: record.parentExternalId,
      sourceVersion: record.sourceVersion,
      reviewStatus: record.reviewStatus,
      payloadSha256: digest,
      metadataJson: canonicalJson(record.metadata),
      lastSeenAt: now,
      updatedAt: existing.payloadSha256 === digest ? existing.updatedAt : now,
    }).where(eq(sourceRecords.id, existing.id));
    if (existing.payloadSha256 !== digest) updatedRecords += 1;
  }

  for (const partner of payload.partners) {
    const source = await sourceRecordByExternalId(
      payload.workspaceId,
      payload.sourceSystem,
      partner.sourceExternalId,
    );
    if (!source) {
      throw new Response(
        `Partner source ${partner.sourceExternalId} was not imported.`,
        { status: 422 },
      );
    }
    const identityKey = await partnerIdentity(partner);
    const [existing] = await db.select().from(businessPartners).where(and(
      eq(businessPartners.workspaceId, payload.workspaceId),
      eq(businessPartners.identityKey, identityKey),
    )).limit(1);
    const partnerValues = {
      partnerType: partner.partnerType,
      name: partner.name,
      email: partner.email,
      phone: partner.phone,
      location: partner.location,
      specialties: partner.specialties,
      recordStatus: partner.recordStatus,
      matchConfidence: partner.matchConfidence,
      metadataJson: canonicalJson(partner.metadata),
      updatedAt: now,
    };
    let partnerId: number;
    if (existing) {
      await db.update(businessPartners).set(partnerValues)
        .where(eq(businessPartners.id, existing.id));
      partnerId = existing.id;
    } else {
      const [inserted] = await db.insert(businessPartners).values({
        workspaceId: payload.workspaceId,
        identityKey,
        ...partnerValues,
        createdAt: now,
      }).returning({ id: businessPartners.id });
      partnerId = inserted.id;
      newPartners += 1;
    }
    await db.insert(businessPartnerSources).values({
      partnerId,
      sourceRecordId: source.id,
      createdAt: now,
    }).onConflictDoNothing();
  }

  for (const project of payload.projects) {
    const source = await sourceRecordByExternalId(
      payload.workspaceId,
      payload.sourceSystem,
      project.sourceExternalId,
    );
    if (!source) {
      throw new Response(
        `Project source ${project.sourceExternalId} was not imported.`,
        { status: 422 },
      );
    }
    let customerImportId: number | null = null;
    if (project.customerSourceSystem && project.customerExternalId) {
      const [customer] = await db.select({
        id: customerImports.id,
      }).from(customerImports).where(and(
        eq(customerImports.workspaceId, payload.workspaceId),
        eq(customerImports.sourceSystem, project.customerSourceSystem),
        eq(customerImports.externalId, project.customerExternalId),
      )).limit(1);
      customerImportId = customer?.id ?? null;
    }
    const customerMatchStatus = customerImportId
      ? "matched"
      : project.customerExternalId
        ? "review"
        : "unmatched";
    const [existing] = await db.select().from(businessProjects).where(and(
      eq(businessProjects.workspaceId, payload.workspaceId),
      eq(businessProjects.externalKey, project.externalKey),
    )).limit(1);
    const projectValues = {
      sourceRecordId: source.id,
      title: project.title,
      location: project.location,
      projectType: project.projectType,
      projectStatus: project.projectStatus,
      customerImportId,
      customerMatchStatus: customerMatchStatus as
        | "matched"
        | "review"
        | "unmatched",
      metadataJson: canonicalJson(project.metadata),
      updatedAt: now,
    };
    if (existing) {
      await db.update(businessProjects).set(projectValues)
        .where(eq(businessProjects.id, existing.id));
    } else {
      await db.insert(businessProjects).values({
        workspaceId: payload.workspaceId,
        externalKey: project.externalKey,
        ...projectValues,
        createdAt: now,
      });
      newProjects += 1;
    }
  }

  for (const review of payload.reviews) {
    const source = await sourceRecordByExternalId(
      payload.workspaceId,
      payload.sourceSystem,
      review.sourceExternalId,
    );
    if (!source) {
      throw new Response(
        `Review source ${review.sourceExternalId} was not imported.`,
        { status: 422 },
      );
    }
    const inserted = await db.insert(importReviewItems).values({
      workspaceId: payload.workspaceId,
      sourceRecordId: source.id,
      entityType: review.entityType,
      reasonCode: review.reasonCode,
      summary: review.summary,
      status: "open",
      createdAt: now,
      resolvedAt: null,
    }).onConflictDoNothing().returning({ id: importReviewItems.id });
    newReviews += inserted.length;
  }

  return {
    workspaceId: payload.workspaceId,
    sourceSystem: payload.sourceSystem,
    requested: {
      records: payload.records.length,
      partners: payload.partners.length,
      projects: payload.projects.length,
      reviews: payload.reviews.length,
    },
    newlyStored: {
      records: newRecords,
      partners: newPartners,
      projects: newProjects,
      reviews: newReviews,
    },
    updatedRecords,
  };
}

export async function getFullImportStatus(workspaceId: string) {
  const normalized = requiredIdentifier(workspaceId, "workspaceId");
  const db = await getDb();
  const [
    recordCounts,
    partnerCounts,
    projectCounts,
    openReviews,
    recentRecords,
  ] = await Promise.all([
    db.select({
      recordType: sourceRecords.recordType,
      reviewStatus: sourceRecords.reviewStatus,
      count: sql<number>`count(*)`,
    }).from(sourceRecords).where(
      eq(sourceRecords.workspaceId, normalized),
    ).groupBy(sourceRecords.recordType, sourceRecords.reviewStatus),
    db.select({
      partnerType: businessPartners.partnerType,
      recordStatus: businessPartners.recordStatus,
      count: sql<number>`count(*)`,
    }).from(businessPartners).where(
      eq(businessPartners.workspaceId, normalized),
    ).groupBy(businessPartners.partnerType, businessPartners.recordStatus),
    db.select({
      projectStatus: businessProjects.projectStatus,
      customerMatchStatus: businessProjects.customerMatchStatus,
      count: sql<number>`count(*)`,
    }).from(businessProjects).where(
      eq(businessProjects.workspaceId, normalized),
    ).groupBy(
      businessProjects.projectStatus,
      businessProjects.customerMatchStatus,
    ),
    db.select({
      entityType: importReviewItems.entityType,
      count: sql<number>`count(*)`,
    }).from(importReviewItems).where(and(
      eq(importReviewItems.workspaceId, normalized),
      eq(importReviewItems.status, "open"),
    )).groupBy(importReviewItems.entityType),
    db.select({
      externalId: sourceRecords.externalId,
      recordType: sourceRecords.recordType,
      title: sourceRecords.title,
      sourceUrl: sourceRecords.sourceUrl,
      reviewStatus: sourceRecords.reviewStatus,
      updatedAt: sourceRecords.updatedAt,
    }).from(sourceRecords).where(
      eq(sourceRecords.workspaceId, normalized),
    ).orderBy(asc(sourceRecords.id)).limit(100),
  ]);
  return {
    workspaceId: normalized,
    recordCounts,
    partnerCounts,
    projectCounts,
    openReviews,
    recentRecords,
  };
}
