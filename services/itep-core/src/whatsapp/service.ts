import {
  createHash,
  createHmac,
  timingSafeEqual,
} from "node:crypto";
import type { PrismaClient } from "@prisma/client";
import type { ActorContext } from "../application/ports.js";
import type { AppConfig } from "../config/env.js";
import type { ConnectorSecretProvider } from "../connectors/ports.js";
import { hasPermission, requirePermission } from "../auth/permissions.js";
import { decryptSecret, encryptSecret } from "../security/totp.js";
import {
  canReadWhatsAppConversation,
  whatsappConversationScope,
} from "./access.js";
import type { WhatsAppCloudApiGateway } from "./gateway.js";

export class WhatsAppService {
  private readonly dataKey: string;

  constructor(
    private readonly prisma: PrismaClient,
    private readonly secrets: ConnectorSecretProvider,
    private readonly gateway: WhatsAppCloudApiGateway,
    private readonly config: AppConfig,
    private readonly now: () => Date = () => new Date(),
  ) {
    if (
      config.NODE_ENV === "production" &&
      (!config.WHATSAPP_APP_SECRET ||
        !config.WHATSAPP_VERIFY_TOKEN ||
        !config.WHATSAPP_DATA_ENCRYPTION_KEY)
    ) {
      throw new Error(
        "WhatsApp app, verification and encryption secrets are required in production",
      );
    }
    this.dataKey =
      config.WHATSAPP_DATA_ENCRYPTION_KEY ??
      config.AUTH_DATA_ENCRYPTION_KEY ??
      config.IDENTITY_SHARED_SECRET;
  }

  verifyChallenge(token: string, challenge: string): string {
    if (
      !this.config.WHATSAPP_VERIFY_TOKEN ||
      !safeEqual(token, this.config.WHATSAPP_VERIFY_TOKEN)
    ) {
      throw new Error("WhatsApp webhook verification failed");
    }
    return challenge;
  }

  verifySignature(rawBody: string, signature: string): void {
    const secret = this.config.WHATSAPP_APP_SECRET;
    if (!secret) throw new Error("WhatsApp app secret is not configured");
    const expected = `sha256=${createHmac("sha256", secret)
      .update(rawBody)
      .digest("hex")}`;
    if (!safeEqual(signature, expected)) {
      throw new Error("WhatsApp webhook signature is invalid");
    }
  }

  async processWebhook(
    rawBody: string,
    payload: WhatsAppWebhookPayload,
  ): Promise<{ accepted: true; duplicate: boolean; processed: number }> {
    const fingerprint = createHash("sha256").update(rawBody).digest("hex");
    const existing = await this.prisma.whatsAppWebhookEvent.findUnique({
      where: { eventFingerprint: fingerprint },
    });
    if (existing) return { accepted: true, duplicate: true, processed: 0 };

    const event = await this.prisma.whatsAppWebhookEvent.create({
      data: {
        eventFingerprint: fingerprint,
        eventType: payload.object ?? "unknown",
        payload: {
          object: payload.object ?? "unknown",
          entryCount: payload.entry?.length ?? 0,
          contentHash: fingerprint,
        },
      },
    });
    let processed = 0;
    try {
      for (const entry of payload.entry ?? []) {
        for (const change of entry.changes ?? []) {
          const value = change.value;
          const phoneNumberId = value.metadata?.phone_number_id;
          if (!phoneNumberId) continue;
          const connector = await this.prisma.connectorAccount.findFirst({
            where: {
              kind: "WHATSAPP_BUSINESS",
              externalAccountId: phoneNumberId,
              status: "ACTIVE",
            },
          });
          if (!connector) continue;
          const contacts = new Map(
            (value.contacts ?? []).map((contact) => [
              contact.wa_id,
              contact.profile?.name,
            ]),
          );
          for (const message of value.messages ?? []) {
            if (!message.id || !message.from) continue;
            const conversation =
              await this.prisma.whatsAppConversation.upsert({
                where: {
                  organizationId_connectorAccountId_waContactHash: {
                    organizationId: connector.organizationId,
                    connectorAccountId: connector.id,
                    waContactHash: this.contactHash(message.from),
                  },
                },
                update: {
                  displayName: contacts.get(message.from),
                  lastMessageAt: this.messageTime(message.timestamp),
                  status: "OPEN",
                },
                create: {
                  organizationId: connector.organizationId,
                  connectorAccountId: connector.id,
                  waContactHash: this.contactHash(message.from),
                  waContactCiphertext: encryptSecret(
                    message.from,
                    this.dataKey,
                  ),
                  displayName: contacts.get(message.from),
                  phoneMasked: maskPhone(message.from),
                  lastMessageAt: this.messageTime(message.timestamp),
                },
              });
            await this.prisma.whatsAppMessage.upsert({
              where: { providerMessageId: message.id },
              update: {},
              create: {
                conversationId: conversation.id,
                providerMessageId: message.id,
                direction: "INBOUND",
                status: "RECEIVED",
                messageType: message.type ?? "unknown",
                bodyCiphertext: this.encryptBody(extractMessageBody(message)),
                mediaId: extractMediaId(message),
                replyToProviderId: message.context?.id,
              },
            });
            processed += 1;
          }
          for (const status of value.statuses ?? []) {
            if (!status.id) continue;
            const mapped = mapStatus(status.status);
            await this.prisma.whatsAppMessage.updateMany({
              where: { providerMessageId: status.id },
              data: {
                status: mapped.status,
                ...(mapped.dateField
                  ? { [mapped.dateField]: this.messageTime(status.timestamp) }
                  : {}),
                errorCode: status.errors?.[0]?.code
                  ? String(status.errors[0].code)
                  : undefined,
                errorMessage: status.errors?.[0]?.title,
              },
            });
            processed += 1;
          }
        }
      }
      await this.prisma.whatsAppWebhookEvent.update({
        where: { id: event.id },
        data: { processedAt: this.now() },
      });
      return { accepted: true, duplicate: false, processed };
    } catch (error) {
      await this.prisma.whatsAppWebhookEvent.update({
        where: { id: event.id },
        data: {
          lastError: error instanceof Error ? error.message : String(error),
        },
      });
      throw error;
    }
  }

  async listConversations(actor: ActorContext, limit = 50) {
    this.requireRead(actor);
    const projectScope = whatsappConversationScope(actor);
    const conversations = await this.prisma.whatsAppConversation.findMany({
      where: {
        organizationId: actor.organizationId,
        ...projectScope,
      },
      orderBy: { lastMessageAt: "desc" },
      take: Math.min(Math.max(limit, 1), 100),
    });
    return conversations.map(
      ({
        waContactHash: _hash,
        waContactCiphertext: _ciphertext,
        ...conversation
      }) => conversation,
    );
  }

  async listMessages(
    actor: ActorContext,
    conversationId: string,
    limit = 100,
  ) {
    const conversation = await this.getConversation(actor, conversationId);
    const messages = await this.prisma.whatsAppMessage.findMany({
      where: { conversationId: conversation.id },
      orderBy: { createdAt: "asc" },
      take: Math.min(Math.max(limit, 1), 200),
    });
    return messages.map((message) => ({
      ...message,
      body: message.bodyCiphertext
        ? decryptSecret(message.bodyCiphertext, this.dataKey)
        : null,
      bodyCiphertext: undefined,
    }));
  }

  async linkConversation(
    actor: ActorContext,
    conversationId: string,
    input: {
      crmCustomerId?: string | null;
      projectId?: string | null;
      assignedUserId?: string | null;
    },
  ) {
    requirePermission(actor, "customer.write");
    const conversation = await this.getConversation(actor, conversationId);
    if (
      input.projectId &&
      actor.projectIds?.length &&
      !actor.permissions.includes("*") &&
      !actor.projectIds.includes(input.projectId)
    ) {
      throw new Error("Project access denied");
    }
    return this.prisma.whatsAppConversation.update({
      where: { id: conversation.id },
      data: input,
    });
  }

  async requestMessage(
    actor: ActorContext,
    conversationId: string,
    input: { body: string; replyToProviderId?: string },
  ) {
    const conversation = await this.getConversation(actor, conversationId);
    if (
      !hasPermission(actor, "whatsapp.send.request") &&
      !hasPermission(actor, "whatsapp.send.direct")
    ) {
      throw new Error("Permission required: whatsapp.send.request");
    }
    const direct = hasPermission(actor, "whatsapp.send.direct");
    const message = await this.prisma.whatsAppMessage.create({
      data: {
        conversationId,
        direction: "OUTBOUND",
        status: direct ? "APPROVED" : "PENDING_APPROVAL",
        messageType: "text",
        bodyCiphertext: this.encryptBody(input.body),
        replyToProviderId: input.replyToProviderId,
        requestedBy: actor.actorId,
        ...(direct
          ? {
              approvedBy: actor.actorId,
              approvedAt: this.now(),
            }
          : {}),
      },
    });
    return direct
      ? this.dispatchMessage(conversation, message.id)
      : { ...message, bodyCiphertext: undefined };
  }

  async approveMessage(actor: ActorContext, messageId: string) {
    requirePermission(actor, "whatsapp.approve");
    const message = await this.prisma.whatsAppMessage.findUniqueOrThrow({
      where: { id: messageId },
      include: { conversation: true },
    });
    if (message.conversation.organizationId !== actor.organizationId) {
      throw new Error("Company access denied");
    }
    if (message.status !== "PENDING_APPROVAL") {
      throw new Error("Only pending messages can be approved");
    }
    await this.prisma.whatsAppMessage.update({
      where: { id: message.id },
      data: {
        status: "APPROVED",
        approvedBy: actor.actorId,
        approvedAt: this.now(),
      },
    });
    return this.dispatchMessage(message.conversation, message.id);
  }

  async rejectMessage(
    actor: ActorContext,
    messageId: string,
    reason: string,
  ) {
    requirePermission(actor, "whatsapp.approve");
    const message = await this.prisma.whatsAppMessage.findUniqueOrThrow({
      where: { id: messageId },
      include: { conversation: true },
    });
    if (message.conversation.organizationId !== actor.organizationId) {
      throw new Error("Company access denied");
    }
    return this.prisma.whatsAppMessage.update({
      where: { id: message.id },
      data: {
        status: "REJECTED",
        rejectedBy: actor.actorId,
        rejectedAt: this.now(),
        rejectionReason: reason,
      },
      select: {
        id: true,
        status: true,
        rejectedBy: true,
        rejectedAt: true,
        rejectionReason: true,
      },
    });
  }

  private async dispatchMessage(
    conversation: {
      id: string;
      connectorAccountId: string;
      waContactCiphertext: string;
    },
    messageId: string,
  ) {
    const message = await this.prisma.whatsAppMessage.findUniqueOrThrow({
      where: { id: messageId },
    });
    const connector = await this.prisma.connectorAccount.findUniqueOrThrow({
      where: { id: conversation.connectorAccountId },
    });
    if (
      connector.kind !== "WHATSAPP_BUSINESS" ||
      connector.status !== "ACTIVE"
    ) {
      throw new Error("WhatsApp connector is not active");
    }
    const body = message.bodyCiphertext
      ? decryptSecret(message.bodyCiphertext, this.dataKey)
      : "";
    try {
      const result = await this.gateway.sendText({
        phoneNumberId: connector.externalAccountId,
        to: decryptSecret(conversation.waContactCiphertext, this.dataKey),
        body,
        accessToken: await this.secrets.getAccessToken(connector.id),
        replyToProviderId: message.replyToProviderId ?? undefined,
      });
      const updated = await this.prisma.whatsAppMessage.update({
        where: { id: message.id },
        data: {
          providerMessageId: result.providerMessageId,
          status: "SENT",
          sentAt: this.now(),
        },
      });
      return { ...updated, bodyCiphertext: undefined };
    } catch (error) {
      await this.prisma.whatsAppMessage.update({
        where: { id: message.id },
        data: {
          status: "FAILED",
          failedAt: this.now(),
          errorMessage:
            error instanceof Error ? error.message.slice(0, 1000) : "Unknown",
        },
      });
      throw error;
    }
  }

  private async getConversation(
    actor: ActorContext,
    conversationId: string,
  ) {
    this.requireRead(actor);
    const conversation = await this.prisma.whatsAppConversation.findUniqueOrThrow(
      { where: { id: conversationId } },
    );
    if (conversation.organizationId !== actor.organizationId) {
      throw new Error("Company access denied");
    }
    if (!canReadWhatsAppConversation(actor, conversation)) {
      throw new Error("Project access denied");
    }
    return conversation;
  }

  private requireRead(actor: ActorContext): void {
    if (
      ![
        "whatsapp.read",
        "whatsapp.read.project",
        "whatsapp.read.own",
      ].some((permission) => hasPermission(actor, permission))
    ) {
      throw new Error("Permission required: whatsapp.read");
    }
  }

  private encryptBody(body: string | null): string | null {
    return body ? encryptSecret(body, this.dataKey) : null;
  }

  private messageTime(value?: string): Date {
    const timestamp = Number(value);
    return Number.isFinite(timestamp) && timestamp > 0
      ? new Date(timestamp * 1000)
      : this.now();
  }

  private contactHash(value: string): string {
    return createHmac("sha256", this.dataKey).update(value).digest("hex");
  }
}

export interface WhatsAppWebhookPayload {
  object?: string;
  entry?: Array<{
    changes?: Array<{
      value: {
        metadata?: { phone_number_id?: string };
        contacts?: Array<{
          wa_id: string;
          profile?: { name?: string };
        }>;
        messages?: WhatsAppInboundMessage[];
        statuses?: Array<{
          id?: string;
          status?: string;
          timestamp?: string;
          errors?: Array<{ code?: number; title?: string }>;
        }>;
      };
    }>;
  }>;
}

interface WhatsAppInboundMessage {
  id?: string;
  from?: string;
  timestamp?: string;
  type?: string;
  text?: { body?: string };
  button?: { text?: string };
  interactive?: {
    button_reply?: { title?: string };
    list_reply?: { title?: string };
  };
  image?: { id?: string; caption?: string };
  document?: { id?: string; caption?: string; filename?: string };
  audio?: { id?: string };
  video?: { id?: string; caption?: string };
  context?: { id?: string };
}

function extractMessageBody(message: WhatsAppInboundMessage): string | null {
  return (
    message.text?.body ??
    message.button?.text ??
    message.interactive?.button_reply?.title ??
    message.interactive?.list_reply?.title ??
    message.image?.caption ??
    message.document?.caption ??
    message.video?.caption ??
    message.document?.filename ??
    null
  );
}

function extractMediaId(message: WhatsAppInboundMessage): string | null {
  return (
    message.image?.id ??
    message.document?.id ??
    message.audio?.id ??
    message.video?.id ??
    null
  );
}

function maskPhone(value: string): string {
  const digits = value.replace(/\D/g, "");
  return digits.length <= 4
    ? `***${digits}`
    : `${digits.slice(0, 2)}***${digits.slice(-4)}`;
}

function mapStatus(value?: string): {
  status: "SENT" | "DELIVERED" | "READ" | "FAILED";
  dateField: "sentAt" | "deliveredAt" | "readAt" | "failedAt";
} {
  if (value === "delivered") {
    return { status: "DELIVERED", dateField: "deliveredAt" };
  }
  if (value === "read") return { status: "READ", dateField: "readAt" };
  if (value === "failed") return { status: "FAILED", dateField: "failedAt" };
  return { status: "SENT", dateField: "sentAt" };
}

function safeEqual(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}
