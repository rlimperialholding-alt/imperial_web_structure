import type { EmailMessage, EmailSender } from "./email-sender.js";

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
    const response = await this.transport.send({
      to: message.to,
      cc: message.cc,
      subject: message.subject,
      text: message.text,
      ...(message.html ? { html: message.html } : {}),
      ...(message.headers ? { headers: message.headers } : {}),
    });

    return { providerMessageId: response.id };
  }
}
