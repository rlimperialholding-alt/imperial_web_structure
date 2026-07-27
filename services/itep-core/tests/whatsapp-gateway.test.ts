import { describe, expect, it, vi } from "vitest";
import { WhatsAppCloudApiGateway } from "../src/whatsapp/gateway.js";
import {
  canReadWhatsAppConversation,
  whatsappConversationScope,
} from "../src/whatsapp/access.js";

describe("WhatsApp Cloud API gateway", () => {
  it("sends only a CRM text message using the dedicated phone-number id", async () => {
    const http = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(init?.headers).toMatchObject({
        authorization: "Bearer secret",
        "content-type": "application/json",
      });
      expect(JSON.parse(String(init?.body))).toEqual({
        messaging_product: "whatsapp",
        recipient_type: "individual",
        to: "36301234567",
        type: "text",
        text: { preview_url: false, body: "Tesztüzenet" },
      });
      return new Response(
        JSON.stringify({ messages: [{ id: "wamid.test-1" }] }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    const gateway = new WhatsAppCloudApiGateway(
      "https://graph.example",
      "v25.0",
      http as typeof fetch,
    );
    await expect(
      gateway.sendText({
        phoneNumberId: "100000000001",
        to: "36301234567",
        body: "Tesztüzenet",
        accessToken: "secret",
      }),
    ).resolves.toEqual({ providerMessageId: "wamid.test-1" });
    expect(http).toHaveBeenCalledWith(
      "https://graph.example/v25.0/100000000001/messages",
      expect.any(Object),
    );
  });

  it("does not expose the access token when the provider rejects a message", async () => {
    const gateway = new WhatsAppCloudApiGateway(
      "https://graph.example",
      "v25.0",
      (async () =>
        new Response(
          JSON.stringify({ error: { code: 190, message: "Invalid token" } }),
          { status: 401, headers: { "content-type": "application/json" } },
        )) as typeof fetch,
    );
    await expect(
      gateway.sendText({
        phoneNumberId: "phone",
        to: "contact",
        body: "message",
        accessToken: "never-log-this-token",
      }),
    ).rejects.not.toThrow("never-log-this-token");
  });
});

describe("WhatsApp tenant and project boundary", () => {
  const customer = {
    actorId: "customer-1",
    organizationId: "company-a",
    roles: ["CUSTOMER"],
    permissions: ["whatsapp.read.own"],
    projectIds: [] as string[],
  };

  it("does not interpret an empty project list as group-wide access", () => {
    expect(whatsappConversationScope(customer)).toEqual({
      OR: [{ assignedUserId: "customer-1" }],
    });
    expect(
      canReadWhatsAppConversation(customer, {
        projectId: null,
        assignedUserId: "another-user",
      }),
    ).toBe(false);
  });

  it("allows assigned projects while full administrators remain unrestricted", () => {
    const projectCustomer = { ...customer, projectIds: ["project-1"] };
    expect(
      canReadWhatsAppConversation(projectCustomer, {
        projectId: "project-1",
        assignedUserId: null,
      }),
    ).toBe(true);
    expect(
      canReadWhatsAppConversation(projectCustomer, {
        projectId: "project-2",
        assignedUserId: null,
      }),
    ).toBe(false);
    expect(
      whatsappConversationScope({ ...customer, permissions: ["*"] }),
    ).toEqual({});
  });
});
