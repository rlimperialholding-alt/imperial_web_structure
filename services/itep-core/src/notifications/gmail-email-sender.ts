import type { EmailMessage, EmailSender } from "./email-sender.js";
import {
  classifyRecipientAudience,
  validateOutboundCopy,
} from "./outbound-copy-guard.js";

export interface GmailTransport {
  send(input: {
    from: string;
    to: string;
    cc: string[];
    subject: string;
    text: string;
    html?: string;
    replyTo?: string;
    headers?: Record<string, string>;
  }): Promise<{ id: string }>;
}

export class GmailEmailSender implements EmailSender {
  constructor(
    private readonly transport: GmailTransport,
    private readonly brandId: string,
    private readonly senderEmail: string,
  ) {}

  async send(message: EmailMessage): Promise<{ providerMessageId: string }> {
    const reservedHeaders = new Set(["from", "sender", "reply-to", "return-path"]);
    if (Object.keys(message.headers ?? {}).some((name) => reservedHeaders.has(name.toLowerCase()))) {
      throw new Error("OUTBOUND_COPY_BLOCKED:reserved_identity_header");
    }
    const verifiedAudience = [message.to, ...message.cc].every(
      (recipient) => classifyRecipientAudience(this.brandId, recipient) === "internal",
    ) ? "internal" : "external";
    if (message.audience === "internal" && verifiedAudience !== "internal") {
      throw new Error("OUTBOUND_COPY_BLOCKED:recipient_audience_mismatch");
    }
    validateOutboundCopy({
      brandId: this.brandId,
      senderEmail: this.senderEmail,
      subject: message.subject,
      text: message.text,
      ...(message.html ? { html: message.html } : {}),
      ...(message.replyTo ? { replyToEmail: message.replyTo } : {}),
      audience: message.audience === "external" ? "external" : verifiedAudience,
    });
    const response = await this.transport.send({
      from: this.senderEmail,
      to: message.to,
      cc: message.cc,
      subject: message.subject,
      text: message.text,
      ...(message.html ? { html: message.html } : {}),
      ...(message.replyTo ? { replyTo: message.replyTo } : {}),
      ...(message.headers ? { headers: message.headers } : {}),
    });

    return { providerMessageId: response.id };
  }
}
