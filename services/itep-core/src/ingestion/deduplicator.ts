import { buildSemanticTaskFingerprint } from "./fingerprint.js";
import type { TaskCandidateDeduplicator } from "./ports.js";
import type { TaskCandidate } from "./types.js";

export interface ExistingTaskLookup {
  findBySource(input: {
    organizationId: string;
    source: string;
    sourceExternalId: string;
  }): Promise<{ id: string } | null>;
  findBySemanticFingerprint(
    fingerprint: string,
  ): Promise<{ id: string } | null>;
}

export class DefaultTaskCandidateDeduplicator
  implements TaskCandidateDeduplicator {
  constructor(private readonly lookup: ExistingTaskLookup) {}

  async findExisting(candidate: TaskCandidate) {
    const sourceMatch = await this.lookup.findBySource({
      organizationId: candidate.organizationId,
      source: candidate.source,
      sourceExternalId: candidate.sourceExternalId,
    });
    if (sourceMatch) {
      return {
        duplicate: true,
        taskId: sourceMatch.id,
        reason: "Azonos forráskülső-azonosítóval már létezik feladat.",
      };
    }

    const fingerprint = buildSemanticTaskFingerprint({
      organizationId: candidate.organizationId,
      title: candidate.title,
      assigneeId: candidate.assigneeId,
      dueAt: candidate.dueAt,
    });
    const semanticMatch =
      await this.lookup.findBySemanticFingerprint(fingerprint);

    return semanticMatch
      ? {
          duplicate: true,
          taskId: semanticMatch.id,
          reason: "Szemantikailag azonos aktív feladat már létezik.",
        }
      : { duplicate: false };
  }
}
