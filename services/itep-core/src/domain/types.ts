export type TaskPriority = "P1" | "P2" | "P3" | "P4";

export type TaskStatus =
  | "DRAFT"
  | "ASSIGNED"
  | "AWAITING_ACKNOWLEDGEMENT"
  | "IN_PROGRESS"
  | "WAITING_EXTERNAL"
  | "BLOCKED"
  | "SUBMITTED"
  | "UNDER_REVIEW"
  | "CHANGES_REQUESTED"
  | "CLOSED"
  | "CANCELLED";

export type AssigneeType =
  | "EMPLOYEE"
  | "MANAGER"
  | "SUBCONTRACTOR"
  | "PARTNER"
  | "EXTERNAL_EXPERT"
  | "SYSTEM";

export type EvidenceType =
  | "EMAIL"
  | "DOCUMENT"
  | "PHOTO"
  | "FILE"
  | "LINK"
  | "SYSTEM_DATA"
  | "SIGNATURE"
  | "APPROVAL"
  | "OTHER";

export type SensitivityLevel =
  | "INTERNAL"
  | "CONFIDENTIAL"
  | "LEGAL"
  | "FINANCIAL"
  | "AUTHORITY"
  | "HR";

export interface ContactPoint {
  email: string;
  phone?: string;
}

export interface EvidenceRequirement {
  type: EvidenceType;
  description: string;
  machineVerifiable: boolean;
}

export interface EvidenceSubmission {
  id: string;
  type: EvidenceType;
  uri: string;
  submittedAt: Date;
  submittedBy: string;
  checksum?: string;
  metadata?: Record<string, unknown>;
}

export interface Task {
  id: string;
  organizationId: string;
  source: string;
  sourceExternalId?: string;
  semanticFingerprint?: string;
  issuerId: string;
  assigneeId: string;
  assigneeType: AssigneeType;
  title: string;
  description: string;
  priority: TaskPriority;
  createdAt: Date;
  dueAt: Date;
  acceptanceCriteria: string;
  evidenceRequirement: EvidenceRequirement;
  evidenceSubmissions: EvidenceSubmission[];
  escalationPersonId: string;
  contact: ContactPoint;
  status: TaskStatus;
  lastCheckedAt?: Date;
  nextCheckAt: Date;
  reminderLevel: number;
  relatedEntityIds: string[];
  dependencies: string[];
  sensitivity: SensitivityLevel;
  acceptedBy?: string;
  acceptedAt?: Date;
  rejectionReason?: string;
  blockedReason?: string;
  cancelledReason?: string;
}

export interface AuditEvent {
  id: string;
  taskId: string;
  eventType: string;
  actorId: string;
  occurredAt: Date;
  payload: Readonly<Record<string, unknown>>;
}
