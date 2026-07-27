export type SourceKind = "GMAIL" | "CALENDAR" | "DRIVE" | "MANUAL" | "WEBHOOK";
export type SourceEventStatus =
  | "RECEIVED"
  | "NORMALIZED"
  | "IGNORED"
  | "TASK_CREATED"
  | "NEEDS_REVIEW"
  | "FAILED";

export interface SourceEvent {
  id: string;
  organizationId: string;
  legalEntityId?: string;
  source: SourceKind;
  externalId: string;
  occurredAt: Date;
  receivedAt: Date;
  actorId?: string;
  subject?: string;
  body?: string;
  participants: string[];
  labels: string[];
  metadata: Record<string, unknown>;
  status: SourceEventStatus;
  fingerprint: string;
}

export interface TaskCandidate {
  sourceEventId: string;
  organizationId: string;
  legalEntityId?: string;
  source: SourceKind;
  sourceExternalId: string;
  title: string;
  description: string;
  issuerId: string;
  assigneeId?: string;
  priority: "P1" | "P2" | "P3" | "P4";
  dueAt?: Date;
  acceptanceCriteria: string;
  evidenceDescription: string;
  escalationPersonId?: string;
  contactEmail?: string;
  confidence: number;
  requiresHumanReview: boolean;
  reasons: string[];
  sensitivity:
    | "INTERNAL"
    | "CONFIDENTIAL"
    | "LEGAL"
    | "FINANCIAL"
    | "AUTHORITY"
    | "HR";
}

export interface IngestionDecision {
  action: "IGNORE" | "CREATE_TASK" | "HUMAN_REVIEW";
  candidate?: TaskCandidate;
  reason: string;
}
