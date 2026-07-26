import { drizzle } from "drizzle-orm/d1";
import * as schema from "./schema";

export async function getDb() {
  const { env } = await import("cloudflare:workers");
  const database = (env as unknown as { DB?: D1Database }).DB;
  if (!database) throw new Error("A CRM adatbázis-kapcsolata nem érhető el.");
  return drizzle(database, { schema });
}

export async function getRuntimeValue(key: string) {
  const { env } = await import("cloudflare:workers");
  return (env as unknown as Record<string, string | undefined>)[key];
}

type DocumentObject = {
  body: ReadableStream;
  size: number;
  httpMetadata?: { contentType?: string };
};

export type DocumentBucket = {
  put(key: string, value: ArrayBuffer, options?: {
    httpMetadata?: { contentType: string };
    customMetadata?: Record<string, string>;
  }): Promise<unknown>;
  get(key: string): Promise<DocumentObject | null>;
  delete(key: string): Promise<void>;
};

export async function getDocumentBucket() {
  const { env } = await import("cloudflare:workers");
  const bucket = (env as unknown as { DOCUMENTS?: DocumentBucket }).DOCUMENTS;
  if (!bucket) throw new Error("A dokumentumtár jelenleg nem érhető el.");
  return bucket;
}
