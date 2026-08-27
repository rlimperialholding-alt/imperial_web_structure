import { z } from "zod";

export const createTaskSchema = z.object({
  organizationId: z.string().min(1),
  legalEntityId: z.string().min(1).optional(),
  source: z.string().min(1),
  issuerId: z.string().min(1),
  assigneeId: z.string().min(1),
  assigneeType: z.enum([
    "EMPLOYEE", "MANAGER", "SUBCONTRACTOR", "PARTNER",
    "EXTERNAL_EXPERT", "SYSTEM",
  ]),
  title: z.string().min(1),
  description: z.string().min(1),
  priority: z.enum(["P1", "P2", "P3", "P4"]),
  dueAt: z.coerce.date(),
  acceptanceCriteria: z.string().min(1),
  evidenceRequirement: z.object({
    type: z.enum([
      "EMAIL", "DOCUMENT", "PHOTO", "FILE", "LINK",
      "SYSTEM_DATA", "SIGNATURE", "APPROVAL", "OTHER",
    ]),
    description: z.string().min(1),
    machineVerifiable: z.boolean(),
  }),
  escalationPersonId: z.string().min(1),
  contact: z.object({
    email: z.string().email(),
    phone: z.string().min(3).optional(),
  }),
  relatedEntityIds: z.array(z.string()).default([]),
  dependencies: z.array(z.string()).default([]),
  sensitivity: z.enum([
    "INTERNAL", "CONFIDENTIAL", "LEGAL",
    "FINANCIAL", "AUTHORITY", "HR",
  ]),
  status: z.enum(["DRAFT", "ASSIGNED"]).optional(),
});

export const transitionSchema = z.object({
  target: z.enum([
    "DRAFT", "ASSIGNED", "AWAITING_ACKNOWLEDGEMENT",
    "IN_PROGRESS", "WAITING_EXTERNAL", "BLOCKED",
    "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED",
    "CLOSED", "CANCELLED",
  ]),
});

export const evidenceSchema = z.object({
  type: z.enum([
    "EMAIL", "DOCUMENT", "PHOTO", "FILE", "LINK",
    "SYSTEM_DATA", "SIGNATURE", "APPROVAL", "OTHER",
  ]),
  uri: z.string().min(1),
  checksum: z.string().optional(),
  metadata: z.record(z.unknown()).optional(),
});
