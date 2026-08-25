export interface EmailMessage {
  to: string;
  cc: string[];
  audience: "external" | "internal";
  subject: string;
  text: string;
  html?: string;
  replyTo?: string;
  headers?: Record<string, string>;
}

export interface EmailSender {
  send(message: EmailMessage): Promise<{ providerMessageId: string }>;
}
