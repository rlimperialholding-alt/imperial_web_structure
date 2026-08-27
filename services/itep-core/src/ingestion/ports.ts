import type {
  IngestionDecision,
  SourceEvent,
  SourceEventStatus,
  TaskCandidate,
} from "./types.js";

export interface SourceEventRepository {
  findByFingerprint(fingerprint: string): Promise<SourceEvent | null>;
  findByExternalIdentity(input: {
    organizationId: string;
    source: SourceEvent["source"];
    externalId: string;
  }): Promise<SourceEvent | null>;
  create(event: SourceEvent): Promise<void>;
  updateStatus(
    id: string,
    status: SourceEventStatus,
    error?: string,
  ): Promise<void>;
}

export interface TaskCandidateDeduplicator {
  findExisting(candidate: TaskCandidate): Promise<{
    duplicate: boolean;
    taskId?: string;
    reason?: string;
  }>;
}

export interface CandidateTaskCreator {
  createFromCandidate(candidate: TaskCandidate): Promise<{ taskId: string }>;
}

export interface IngestionReviewQueue {
  enqueue(input: {
    event: SourceEvent;
    decision: IngestionDecision;
    createdAt: Date;
  }): Promise<void>;
}
