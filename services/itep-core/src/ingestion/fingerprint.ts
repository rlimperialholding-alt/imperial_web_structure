import { createHash } from "node:crypto";
import type { SourceEvent } from "./types.js";

export function buildSourceFingerprint(input: {
  organizationId: string;
  source: string;
  externalId: string;
  subject?: string;
  occurredAt: Date;
}): string {
  return createHash("sha256")
    .update([
      input.organizationId,
      input.source,
      input.externalId,
      normalize(input.subject ?? ""),
      input.occurredAt.toISOString(),
    ].join("|"))
    .digest("hex");
}

export function buildSemanticTaskFingerprint(input: {
  organizationId: string;
  title: string;
  assigneeId?: string;
  dueAt?: Date;
}): string {
  return createHash("sha256")
    .update([
      input.organizationId,
      normalize(input.title),
      normalize(input.assigneeId ?? ""),
      input.dueAt?.toISOString().slice(0, 10) ?? "",
    ].join("|"))
    .digest("hex");
}

function normalize(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}
