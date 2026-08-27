import { createHash } from "node:crypto";

import type { EmailMessage, EmailSender } from "./email-sender.js";

const DAILY_PUBLICATION_DIGEST = "daily_publication_digest";
const DAILY_PUBLICATION_SUBJECT =
  /^Napi automatikus publikációs összesítő – (\d{4}-\d{2}-\d{2})$/u;

function normalizeRecipient(value: string): string {
  return value.trim().toLocaleLowerCase("en-US");
}

export function publicationDigestIdempotencyKey(input: {
  messageType: string;
  recipient: string;
  localReportDate: string;
}): string {
  return createHash("sha256")
    .update(
      `${input.messageType}${normalizeRecipient(input.recipient)}${input.localReportDate}`,
      "utf8",
    )
    .digest("hex");
}

function effectiveHeaders(message: EmailMessage): Record<string, string> | undefined {
  const subjectDate = DAILY_PUBLICATION_SUBJECT.exec(message.subject)?.[1];
  const identity = message.deliveryIdentity ??
    (subjectDate
      ? { messageType: DAILY_PUBLICATION_DIGEST, localReportDate: subjectDate }
      : undefined);
  if (identity?.messageType !== DAILY_PUBLICATION_DIGEST) {
    return message.headers;
  }
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(identity.localReportDate)) {
    throw new Error("daily_publication_digest_local_report_date_invalid");
  }
  return {
    ...(message.headers ?? {}),
    "X-Imperial-Idempotency-Key": publicationDigestIdempotencyKey({
      messageType: DAILY_PUBLICATION_DIGEST,
      recipient: message.to,
      localReportDate: identity.localReportDate,
    }),
  };
}

export interface GmailTransport {
  send(input: {
    to: string;
    cc: string[];
    subject: string;
    text: string;
    html?: string;
    headers?: Record<string, string>;
  }): Promise<{ id: string }>;
}

export class GmailEmailSender implements EmailSender {
  constructor(private readonly transport: GmailTransport) {}

  async send(message: EmailMessage): Promise<{ providerMessageId: string }> {
    const headers = effectiveHeaders(message);
    const response = await this.transport.send({
      to: message.to,
      cc: message.cc,
      subject: message.subject,
      text: message.text,
      ...(message.html ? { html: message.html } : {}),
      ...(headers ? { headers } : {}),
    });

    return { providerMessageId: response.id };
  }
}
