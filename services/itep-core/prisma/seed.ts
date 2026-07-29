import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const now = new Date();
  const defaultOrganizationId =
    process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding";
  await prisma.authOrganization.upsert({
    where: { id: defaultOrganizationId },
    create: {
      id: defaultOrganizationId,
      displayName: "Imperial Holding",
    },
    update: {},
  });
  await prisma.connectorAccount.upsert({
    where: {
      organizationId_kind_externalAccountId: {
        organizationId: "imperial-holding",
        kind: "GMAIL",
        externalAccountId: "office@example.invalid",
      },
    },
    create: {
      id: "connector-demo-gmail",
      organizationId: "imperial-holding",
      kind: "GMAIL",
      externalAccountId: "office@example.invalid",
      displayName: "Demo Gmail connector",
      status: "DISCONNECTED",
      scopes: ["gmail.readonly"],
      createdAt: now,
      updatedAt: now,
    },
    update: {},
  });

  if ((process.env.BUSINESS_CONNECTORS_MODE ?? "disabled") === "read-only") {
    const organizationId =
      process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding";
    const connectors = [
      {
        id: process.env.BILLINGO_CONNECTOR_ID ?? "billingo-live",
        kind: "BILLINGO" as const,
        externalAccountId:
          process.env.BILLINGO_EXTERNAL_ACCOUNT_ID ?? "all",
        displayName: "Billingo – read-only invoice data",
        scopes: ["invoices.read"],
      },
      {
        id: process.env.META_ADS_CONNECTOR_ID ?? "meta-ads-live",
        kind: "META_ADS" as const,
        externalAccountId: process.env.META_ADS_AD_ACCOUNT_ID,
        displayName: "Meta Ads – read-only campaign insights",
        scopes: ["ads_read", "read_insights"],
      },
      {
        id: process.env.GOOGLE_ADS_CONNECTOR_ID ?? "google-ads-live",
        kind: "GOOGLE_ADS" as const,
        externalAccountId: process.env.GOOGLE_ADS_CUSTOMER_ID,
        displayName: "Google Ads – read-only campaign metrics",
        scopes: [
          "https://www.googleapis.com/auth/adwords",
          "account.read-only",
        ],
      },
    ];
    for (const connector of connectors) {
      if (!connector.externalAccountId) continue;
      await prisma.connectorAccount.upsert({
        where: {
          organizationId_kind_externalAccountId: {
            organizationId,
            kind: connector.kind,
            externalAccountId: connector.externalAccountId,
          },
        },
        create: {
          id: connector.id,
          organizationId,
          kind: connector.kind,
          externalAccountId: connector.externalAccountId,
          displayName: connector.displayName,
          status: "ACTIVE",
          scopes: connector.scopes,
        },
        update: {
          displayName: connector.displayName,
          status: "ACTIVE",
          scopes: connector.scopes,
        },
      });
    }
  }

  if (process.env.WHATSAPP_PHONE_NUMBER_ID) {
    await prisma.connectorAccount.upsert({
      where: {
        organizationId_kind_externalAccountId: {
          organizationId: defaultOrganizationId,
          kind: "WHATSAPP_BUSINESS",
          externalAccountId: process.env.WHATSAPP_PHONE_NUMBER_ID,
        },
      },
      create: {
        id: process.env.WHATSAPP_CONNECTOR_ID ?? "whatsapp-live",
        organizationId: defaultOrganizationId,
        kind: "WHATSAPP_BUSINESS",
        externalAccountId: process.env.WHATSAPP_PHONE_NUMBER_ID,
        displayName: "WhatsApp Business – CRM customer service",
        status: "ACTIVE",
        scopes: [
          "whatsapp_business_management",
          "whatsapp_business_messaging",
        ],
      },
      update: {
        status: "ACTIVE",
        displayName: "WhatsApp Business – CRM customer service",
      },
    });
  }

  console.log("Seed completed.");
}

main()
  .catch((error) => {
    console.error(error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
