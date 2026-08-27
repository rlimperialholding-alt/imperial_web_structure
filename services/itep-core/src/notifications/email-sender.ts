export interface EmailMessage {
  to: string;
  cc: string[];
  subject: string;
  text: string;
  html?: string;
  headers?: Record<string, string>;
  deliveryIdentity?: {
    messageType: string;
    localReportDate: string;
  };
}

export interface EmailSender {
  send(message: EmailMessage): Promise<{ providerMessageId: string }>;
}
