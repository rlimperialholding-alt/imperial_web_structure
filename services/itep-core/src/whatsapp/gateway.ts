export interface WhatsAppSendInput {
  phoneNumberId: string;
  to: string;
  body: string;
  accessToken: string;
  replyToProviderId?: string;
}

export interface WhatsAppSendResult {
  providerMessageId: string;
}

export class WhatsAppCloudApiGateway {
  constructor(
    private readonly baseUrl: string,
    private readonly apiVersion: string,
    private readonly http: typeof fetch = fetch,
  ) {}

  async sendText(input: WhatsAppSendInput): Promise<WhatsAppSendResult> {
    const response = await this.http(
      `${this.baseUrl.replace(/\/$/, "")}/${this.apiVersion}/${
        input.phoneNumberId
      }/messages`,
      {
        method: "POST",
        headers: {
          authorization: `Bearer ${input.accessToken}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({
          messaging_product: "whatsapp",
          recipient_type: "individual",
          to: input.to,
          type: "text",
          ...(input.replyToProviderId
            ? { context: { message_id: input.replyToProviderId } }
            : {}),
          text: { preview_url: false, body: input.body },
        }),
      },
    );
    const payload = (await response.json().catch(() => ({}))) as {
      messages?: Array<{ id?: string }>;
      error?: { code?: number; message?: string };
    };
    if (!response.ok || !payload.messages?.[0]?.id) {
      throw new Error(
        `WhatsApp send failed (${response.status}): ${
          payload.error?.code ?? "UNKNOWN"
        } ${payload.error?.message ?? ""}`.trim(),
      );
    }
    return { providerMessageId: payload.messages[0].id };
  }
}
