import type { GmailHistoryGateway } from "./gmail-sync-adapter.js";
import type { CalendarChangesGateway } from "./calendar-sync-adapter.js";
import type { DriveChangesGateway } from "./drive-sync-adapter.js";

interface GoogleErrorPayload {
  error?: { code?: number; message?: string; status?: string };
}

async function googleJson<T>(url: string, accessToken: string): Promise<T> {
  const response = await fetch(url, {
    headers: { authorization: `Bearer ${accessToken}`, accept: "application/json" },
  });
  if (!response.ok) {
    let details: GoogleErrorPayload | undefined;
    try { details = (await response.json()) as GoogleErrorPayload; } catch { details = undefined; }
    const message = details?.error?.message ?? response.statusText;
    throw new Error(`Google API ${response.status}: ${message}`);
  }
  return (await response.json()) as T;
}

function decodeBase64Url(value?: string): string | undefined {
  if (!value) return undefined;
  return Buffer.from(value, "base64url").toString("utf8");
}

function collectBody(part: any): string | undefined {
  if (!part) return undefined;
  if (part.mimeType === "text/plain" && part.body?.data) return decodeBase64Url(part.body.data);
  for (const child of part.parts ?? []) {
    const found = collectBody(child);
    if (found) return found;
  }
  return decodeBase64Url(part.body?.data);
}

export class GoogleGmailHistoryGateway implements GmailHistoryGateway {
  async listChanges(input: {
    accessToken: string;
    externalAccountId: string;
    historyId?: string;
  }) {
    let messageIds: string[] = [];
    let nextHistoryId = input.historyId;

    if (input.historyId) {
      const historyUrl = new URL("https://gmail.googleapis.com/gmail/v1/users/me/history");
      historyUrl.searchParams.set("startHistoryId", input.historyId);
      historyUrl.searchParams.set("historyTypes", "messageAdded");
      historyUrl.searchParams.set("maxResults", "100");
      const history = await googleJson<any>(historyUrl.toString(), input.accessToken);
      messageIds = [...new Set<string>((history.history ?? []).flatMap((h: any) =>
        (h.messagesAdded ?? []).map((m: any) => m.message?.id).filter((id: unknown): id is string => typeof id === "string"),
      ))];
      nextHistoryId = history.historyId ?? input.historyId;
    } else {
      const list = await googleJson<any>(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=25&q=newer_than:7d",
        input.accessToken,
      );
      messageIds = (list.messages ?? []).map((item: any) => item.id);
    }

    const messages = [];
    for (const messageId of messageIds) {
      const message = await googleJson<any>(
        `https://gmail.googleapis.com/gmail/v1/users/me/messages/${encodeURIComponent(messageId)}?format=full`,
        input.accessToken,
      );
      const headers = Object.fromEntries(
        (message.payload?.headers ?? []).map((h: any) => [String(h.name).toLowerCase(), h.value]),
      );
      const bodyText = collectBody(message.payload);
      messages.push({
        messageId,
        ...(message.threadId ? { threadId: String(message.threadId) } : {}),
        internalDate: new Date(Number(message.internalDate ?? Date.now())),
        from: String(headers.from ?? input.externalAccountId),
        to: String(headers.to ?? "").split(",").map((v) => v.trim()).filter(Boolean),
        cc: String(headers.cc ?? "").split(",").map((v) => v.trim()).filter(Boolean),
        ...(headers.subject ? { subject: String(headers.subject) } : {}),
        ...(bodyText ? { bodyText } : {}),
        labels: Array.isArray(message.labelIds) ? message.labelIds.map(String) : [],
      });
      nextHistoryId = message.historyId ?? nextHistoryId;
    }
    return {
      messages,
      ...(nextHistoryId ? { nextHistoryId } : {}),
    };
  }
}

export class GoogleCalendarChangesGateway implements CalendarChangesGateway {
  async listChanges(input: {
    accessToken: string;
    externalAccountId: string;
    syncToken?: string;
  }) {
    const url = new URL(
      `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(input.externalAccountId)}/events`,
    );
    url.searchParams.set("singleEvents", "true");
    url.searchParams.set("showDeleted", "true");
    url.searchParams.set("maxResults", "250");
    if (input.syncToken) url.searchParams.set("syncToken", input.syncToken);
    else url.searchParams.set("timeMin", new Date(Date.now() - 7 * 86400000).toISOString());

    const data = await googleJson<any>(url.toString(), input.accessToken);
    return {
      events: (data.items ?? []).map((event: any) => ({
        eventId: event.id,
        startAt: new Date(event.start?.dateTime ?? `${event.start?.date}T00:00:00Z`),
        endAt: new Date(event.end?.dateTime ?? `${event.end?.date}T00:00:00Z`),
        title: event.summary ?? "Névtelen naptáresemény",
        description: event.description,
        organizer: event.organizer?.email ?? input.externalAccountId,
        attendees: (event.attendees ?? []).map((a: any) => a.email).filter(Boolean),
        status: event.status ?? "confirmed",
      })),
      nextSyncToken: data.nextSyncToken ?? input.syncToken,
    };
  }
}

export class GoogleDriveChangesGateway implements DriveChangesGateway {
  async listChanges(input: { accessToken: string; pageToken?: string }) {
    let pageToken = input.pageToken;
    if (!pageToken) {
      const initial = await googleJson<any>(
        "https://www.googleapis.com/drive/v3/changes/startPageToken",
        input.accessToken,
      );
      pageToken = initial.startPageToken;
    }
    const url = new URL("https://www.googleapis.com/drive/v3/changes");
    if (!pageToken) throw new Error("Google Drive start page token missing");
    url.searchParams.set("pageToken", pageToken);
    url.searchParams.set("pageSize", "100");
    url.searchParams.set("spaces", "drive");
    url.searchParams.set("fields", "changes(fileId,removed,time,file(id,name,mimeType,modifiedTime,createdTime,parents,webViewLink,trashed)),newStartPageToken,nextPageToken");
    const data = await googleJson<any>(url.toString(), input.accessToken);
    return {
      changes: (data.changes ?? []).map((change: any) => ({
        fileId: String(change.fileId),
        removed: Boolean(change.removed),
        ...(change.file?.name ? { name: String(change.file.name) } : {}),
        ...(change.file?.mimeType ? { mimeType: String(change.file.mimeType) } : {}),
        changedAt: new Date(change.time ?? change.file?.modifiedTime ?? Date.now()),
        ...(change.file?.createdTime ? { createdAt: new Date(change.file.createdTime) } : {}),
        parentIds: Array.isArray(change.file?.parents) ? change.file.parents.map(String) : [],
        ...(change.file?.webViewLink ? { webViewLink: String(change.file.webViewLink) } : {}),
        trashed: Boolean(change.file?.trashed),
      })),
      nextPageToken: data.nextPageToken ?? data.newStartPageToken ?? pageToken,
    };
  }
}
