import { and, asc, eq, gt } from "drizzle-orm";
import { getDb, getDocumentBucket } from "@/db";
import { migrationBatches, migrationDocuments } from "@/db/schema";
import { safeFileName, sha256Hex, validateDocumentFile } from "@/lib/document-upload";

const MAX_DOCUMENTS_PER_BATCH = 100;
const identifierPattern = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/;

type ManifestDocument = {
  externalId: string;
  title: string;
  metadata?: Record<string, unknown>;
};

type MigrationManifest = {
  idempotencyKey: string;
  workspaceId: string;
  sourceSystem: string;
  documents: ManifestDocument[];
};

function requiredIdentifier(value: unknown, name: string) {
  const normalized = String(value ?? "").trim();
  if (!identifierPattern.test(normalized)) {
    throw new Response(`${name} érvénytelen.`, { status: 400 });
  }
  return normalized;
}

function parseManifest(value: FormDataEntryValue | null): MigrationManifest {
  if (typeof value !== "string") {
    throw new Response("A manifest mező megadása kötelező.", { status: 400 });
  }
  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(value) as Record<string, unknown>;
  } catch {
    throw new Response("A manifest nem érvényes JSON.", { status: 400 });
  }
  const documents = Array.isArray(parsed.documents) ? parsed.documents : [];
  if (!documents.length || documents.length > MAX_DOCUMENTS_PER_BATCH) {
    throw new Response("Egy migrációs csomag 1–100 dokumentumot tartalmazhat.", {
      status: 400,
    });
  }
  const normalizedDocuments = documents.map((item, index) => {
    const record = item && typeof item === "object"
      ? item as Record<string, unknown>
      : {};
    const title = String(record.title ?? "").trim().slice(0, 180);
    if (!title) {
      throw new Response(`A(z) ${index + 1}. dokumentum címe hiányzik.`, {
        status: 400,
      });
    }
    const metadata = record.metadata;
    if (metadata !== undefined && (
      !metadata ||
      typeof metadata !== "object" ||
      Array.isArray(metadata)
    )) {
      throw new Response(`A(z) ${index + 1}. dokumentum metadata mezője érvénytelen.`, {
        status: 400,
      });
    }
    return {
      externalId: requiredIdentifier(record.externalId, "externalId"),
      title,
      ...(metadata ? { metadata: metadata as Record<string, unknown> } : {}),
    };
  });
  if (new Set(normalizedDocuments.map((item) => item.externalId)).size !== normalizedDocuments.length) {
    throw new Response("Egy csomagon belül az externalId értékeknek egyedinek kell lenniük.", {
      status: 400,
    });
  }
  return {
    idempotencyKey: requiredIdentifier(parsed.idempotencyKey, "idempotencyKey"),
    workspaceId: requiredIdentifier(parsed.workspaceId, "workspaceId"),
    sourceSystem: requiredIdentifier(parsed.sourceSystem, "sourceSystem"),
    documents: normalizedDocuments,
  };
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

async function payloadFingerprint(
  manifest: MigrationManifest,
  documents: { sha256: string; size: number; fileName: string }[],
) {
  const bytes = new TextEncoder().encode(canonicalJson({ manifest, documents }));
  return toHex(await crypto.subtle.digest("SHA-256", bytes));
}

function objectSegment(value: string) {
  return encodeURIComponent(value).replaceAll("%", "_");
}

export async function importMigrationBatch(request: Request) {
  const form = await request.formData();
  const manifest = parseManifest(form.get("manifest"));
  const files = form.getAll("documents");
  if (
    files.length !== manifest.documents.length ||
    files.some((item) => !(item instanceof File))
  ) {
    throw new Response("A manifest és a feltöltött dokumentumok száma nem egyezik.", {
      status: 400,
    });
  }

  const validated = await Promise.all(
    (files as File[]).map(async (file) => {
      const data = await validateDocumentFile(file);
      return {
        data,
        fileName: safeFileName(file.name),
        contentType: file.type,
        size: file.size,
        sha256: await sha256Hex(data),
      };
    }),
  );
  const payloadSha256 = await payloadFingerprint(manifest, validated);
  const db = await getDb();
  const now = new Date().toISOString();

  await db.insert(migrationBatches).values({
    idempotencyKey: manifest.idempotencyKey,
    workspaceId: manifest.workspaceId,
    sourceSystem: manifest.sourceSystem,
    payloadSha256,
    requestedCount: manifest.documents.length,
    storedCount: 0,
    status: "processing",
    createdAt: now,
    completedAt: null,
  }).onConflictDoNothing();

  const [batch] = await db.select().from(migrationBatches)
    .where(eq(migrationBatches.idempotencyKey, manifest.idempotencyKey))
    .limit(1);
  if (
    !batch ||
    batch.workspaceId !== manifest.workspaceId ||
    batch.sourceSystem !== manifest.sourceSystem ||
    batch.payloadSha256 !== payloadSha256 ||
    batch.requestedCount !== manifest.documents.length
  ) {
    throw new Response("Az idempotencyKey már más tartalmú csomaghoz tartozik.", {
      status: 409,
    });
  }

  const bucket = await getDocumentBucket();
  let newlyStored = 0;
  for (let index = 0; index < manifest.documents.length; index += 1) {
    const item = manifest.documents[index];
    const file = validated[index];
    const [existing] = await db.select().from(migrationDocuments).where(and(
      eq(migrationDocuments.workspaceId, manifest.workspaceId),
      eq(migrationDocuments.sourceSystem, manifest.sourceSystem),
      eq(migrationDocuments.externalId, item.externalId),
    )).limit(1);
    if (existing) {
      if (existing.sha256 !== file.sha256) {
        throw new Response(
          `A(z) ${item.externalId} forrásazonosító már eltérő tartalommal szerepel.`,
          { status: 409 },
        );
      }
      continue;
    }

    const objectKey = [
      "migrations",
      objectSegment(manifest.workspaceId),
      objectSegment(manifest.sourceSystem),
      objectSegment(item.externalId),
      `${file.sha256}-${objectSegment(file.fileName)}`,
    ].join("/");
    await bucket.put(objectKey, file.data, {
      httpMetadata: { contentType: file.contentType },
      customMetadata: {
        batchId: manifest.idempotencyKey,
        workspaceId: manifest.workspaceId,
        sourceSystem: manifest.sourceSystem,
        externalId: item.externalId,
        sha256: file.sha256,
      },
    });
    const inserted = await db.insert(migrationDocuments).values({
      batchId: manifest.idempotencyKey,
      workspaceId: manifest.workspaceId,
      sourceSystem: manifest.sourceSystem,
      externalId: item.externalId,
      title: item.title,
      fileName: file.fileName,
      contentType: file.contentType,
      size: file.size,
      sha256: file.sha256,
      objectKey,
      metadataJson: canonicalJson(item.metadata ?? {}),
      migratedAt: now,
    }).onConflictDoNothing().returning({ id: migrationDocuments.id });
    newlyStored += inserted.length;
  }

  const stored = await db.select().from(migrationDocuments)
    .where(eq(migrationDocuments.batchId, manifest.idempotencyKey))
    .orderBy(asc(migrationDocuments.id));
  if (stored.length !== manifest.documents.length) {
    throw new Response("A migrációs csomag tárolása nem fejeződött be.", {
      status: 500,
    });
  }
  const completedAt = new Date().toISOString();
  await db.update(migrationBatches).set({
    storedCount: stored.length,
    status: "completed",
    completedAt,
  }).where(eq(migrationBatches.idempotencyKey, manifest.idempotencyKey));

  return {
    batch: {
      idempotencyKey: manifest.idempotencyKey,
      workspaceId: manifest.workspaceId,
      sourceSystem: manifest.sourceSystem,
      requestedCount: manifest.documents.length,
      storedCount: stored.length,
      payloadSha256,
      status: "completed" as const,
      completedAt,
    },
    documents: stored.map(publicDocument),
    newlyStored,
    duplicateCount: stored.length - newlyStored,
  };
}

export async function getMigrationBatch(idempotencyKey: string) {
  const db = await getDb();
  const [batch] = await db.select().from(migrationBatches)
    .where(eq(migrationBatches.idempotencyKey, idempotencyKey))
    .limit(1);
  if (!batch) return null;
  const documents = await db.select().from(migrationDocuments)
    .where(eq(migrationDocuments.batchId, idempotencyKey))
    .orderBy(asc(migrationDocuments.id));
  return { batch, documents: documents.map(publicDocument) };
}

export async function getMigrationDocument(id: number) {
  const db = await getDb();
  const [document] = await db.select().from(migrationDocuments)
    .where(eq(migrationDocuments.id, id))
    .limit(1);
  return document ?? null;
}

export async function listMigrationActivities(
  workspaceId: string,
  cursor: number,
  limit: number,
) {
  const db = await getDb();
  const rows = await db.select().from(migrationDocuments).where(and(
    eq(migrationDocuments.workspaceId, workspaceId),
    gt(migrationDocuments.id, cursor),
  )).orderBy(asc(migrationDocuments.id)).limit(limit + 1);
  const hasMore = rows.length > limit;
  const page = rows.slice(0, limit);
  return {
    activities: page.map((document) => ({
      id: `migration-document-${document.id}`,
      leadId: document.externalId,
      type: "DOCUMENT_MIGRATED",
      title: document.title,
      description: `Tárolt migrációs dokumentum: ${document.fileName} (SHA-256: ${document.sha256})`,
      ownerEmail: "migration-engine@imperial.local",
      occurredAt: document.migratedAt,
      status: "COMPLETED",
      priority: "normal",
    })),
    ...(hasMore ? { nextCursor: String(page.at(-1)?.id ?? cursor) } : {}),
  };
}

function publicDocument(document: typeof migrationDocuments.$inferSelect) {
  return {
    id: document.id,
    externalId: document.externalId,
    title: document.title,
    fileName: document.fileName,
    contentType: document.contentType,
    size: document.size,
    sha256: document.sha256,
    migratedAt: document.migratedAt,
    downloadUrl: `/api/integrations/migration/documents/${document.id}`,
  };
}
