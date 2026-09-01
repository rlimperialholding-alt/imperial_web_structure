import { buildSourceFingerprint } from "./fingerprint.js";
import type { SourceEvent } from "./types.js";

export interface GmailRawEvent {
  organizationId: string;
  messageId: string;
  threadId?: string;
  internalDate: Date;
  from: string;
  to: string[];
  cc?: string[];
  subject?: string;
  bodyText?: string;
  labels?: string[];
  actorId?: string;
}

export interface CalendarRawEvent {
  organizationId: string;
  eventId: string;
  startAt: Date;
  endAt: Date;
  title: string;
  description?: string;
  organizer: string;
  attendees: string[];
  status: string;
  actorId?: string;
}

export function normalizeGmailEvent(
  raw: GmailRawEvent,
  receivedAt: Date,
): SourceEvent {
  const participants = [
    raw.from,
    ...raw.to,
    ...(raw.cc ?? []),
  ].filter(Boolean);

  return {
    id: `SRC-GMAIL-${raw.messageId}`,
    organizationId: raw.organizationId,
    source: "GMAIL",
    externalId: raw.messageId,
    occurredAt: raw.internalDate,
    receivedAt,
    ...(raw.actorId ? { actorId: raw.actorId } : {}),
    ...(raw.subject ? { subject: raw.subject } : {}),
    ...(raw.bodyText ? { body: raw.bodyText } : {}),
    participants,
    labels: raw.labels ?? [],
    metadata: {
      ...(raw.threadId ? { threadId: raw.threadId } : {}),
      from: raw.from,
      to: raw.to,
      cc: raw.cc ?? [],
    },
    status: "NORMALIZED",
    fingerprint: buildSourceFingerprint({
      organizationId: raw.organizationId,
      source: "GMAIL",
      externalId: raw.messageId,
      subject: raw.subject,
      occurredAt: raw.internalDate,
    }),
  };
}

export function normalizeCalendarEvent(
  raw: CalendarRawEvent,
  receivedAt: Date,
): SourceEvent {
  return {
    id: `SRC-CALENDAR-${raw.eventId}`,
    organizationId: raw.organizationId,
    source: "CALENDAR",
    externalId: raw.eventId,
    occurredAt: raw.startAt,
    receivedAt,
    ...(raw.actorId ? { actorId: raw.actorId } : {}),
    subject: raw.title,
    ...(raw.description ? { body: raw.description } : {}),
    participants: [raw.organizer, ...raw.attendees],
    labels: [raw.status],
    metadata: {
      startAt: raw.startAt.toISOString(),
      endAt: raw.endAt.toISOString(),
      organizer: raw.organizer,
      attendees: raw.attendees,
      status: raw.status,
    },
    status: "NORMALIZED",
    fingerprint: buildSourceFingerprint({
      organizationId: raw.organizationId,
      source: "CALENDAR",
      externalId: raw.eventId,
      subject: raw.title,
      occurredAt: raw.startAt,
    }),
  };
}
