export interface EmailMessage {
  to: string;
  cc: string[];
  subject: string;
  text: string;
  html?: string;
  headers?: Record<string, string>;
}

export interface EmailSender {
  send(message: EmailMessage): Promise<{ providerMessageId: string }>;
}
