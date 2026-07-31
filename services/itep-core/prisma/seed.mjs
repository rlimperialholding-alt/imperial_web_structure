// Plain-Node compatibility seed used by the integrated repository validator.
// The canonical seed command is `npm run seed` (prisma/seed.ts).
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
const organizationId =
  process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding";
await prisma.authOrganization.upsert({
  where: { id: organizationId },
  create: {
    id: organizationId,
    displayName: "Imperial Holding",
  },
  update: {},
});
const companies = [
  ["prefab-keszhazepito", "Prefab Készházépítő Kft."],
  ["bautica-work", "Bautica Work Kft."],
  ["baufreund-ingatlanfejleszto", "Baufreund Ingatlanfejlesztő Kft."],
  ["imperial-holding-keszhazepito", "Imperial Holding Készházépítő Kft."],
  [
    "imperial-holding-csaladi-haz-epito-es-generalkivitelezo",
    "Imperial Holding Családi Ház Építő és Generálkivitelező Kft.",
  ],
  [
    "imperial-holding-mernoki-es-tanacsado",
    "Imperiál Holding Mérnöki és Tanácsadó Iroda Kft.",
  ],
  ["danish-fabrik", "Danish Fabrik Kft."],
  ["casa-moderna", "Casa Moderna Kft."],
  ["feszek-tuzep", "Fészek Tüzép Bt."],
  ["vitruvius", "Vitruvius Kft."],
  ["property-360", "Property 360 Kft."],
  ["everyday-homes", "Everyday Homes Kft."],
];

for (const [slug, legalName] of companies) {
  const id = `${organizationId}:${slug}`;
  await prisma.legalEntity.upsert({
    where: { id },
    create: {
      id,
      organizationId,
      slug,
      legalName,
      status: "ACTIVE",
      metadata: {
        source: "initial-user-supplied-company-list",
        legalIdentifiersVerified: false,
      },
    },
    update: { legalName, status: "ACTIVE" },
  });

  for (const [kind, label, scopes] of [
    ["BILLINGO", "Billingo", ["invoices.read"]],
    ["BANK", "Bank", ["accounts.read", "transactions.read"]],
    [
      "GOVERNMENT_PORTAL",
      "Cégkapu / hatósági tárhely",
      ["messages.read", "notifications.read"],
    ],
  ]) {
    const connectorId = `${kind.toLowerCase().replaceAll("_", "-")}-${slug}`;
    await prisma.connectorAccount.upsert({
      where: { id: connectorId },
      create: {
        id: connectorId,
        organizationId,
        kind,
        scope: "LEGAL_ENTITY",
        scopeKey: id,
        legalEntityId: id,
        externalAccountId: "unconfigured",
        displayName: `${label} – ${legalName}`,
        status: "DISCONNECTED",
        scopes,
        configuration: {
          credentialReference: connectorId,
          provisioningState: "AWAITING_CREDENTIALS",
        },
      },
      update: { displayName: `${label} – ${legalName}` },
    });
  }
}

await prisma.connectorAccount.upsert({
  where: { id: "connector-demo-gmail" },
  create: {
    id: "connector-demo-gmail",
    organizationId,
    kind: "GMAIL",
    scope: "GROUP",
    scopeKey: "GROUP",
    externalAccountId: "office@example.invalid",
    displayName: "Demo Gmail connector",
    status: "DISCONNECTED",
    scopes: ["gmail.readonly"],
  },
  update: {},
});

const workspaceId = process.env.CRM_WORKSPACE_ID;
if (workspaceId) {
  await prisma.connectorAccount.upsert({
    where: { id: process.env.ITEP_CRM_CONNECTOR_ID ?? "crm-live" },
    create: {
      id: process.env.ITEP_CRM_CONNECTOR_ID ?? "crm-live",
      organizationId,
      kind: "CRM",
      scope: "GROUP",
      scopeKey: "GROUP",
      externalAccountId: workspaceId,
      displayName: "Imperial Sales CRM – internal read-only",
      status: "ACTIVE",
      scopes: ["activities.read", "leads.read", "deals.read"],
    },
    update: {
      status: "ACTIVE",
      displayName: "Imperial Sales CRM – internal read-only",
      scopes: ["activities.read", "leads.read", "deals.read"],
    },
  });
}

const mode = process.env.BUSINESS_CONNECTORS_MODE ?? "disabled";
if (mode === "read-only") {
  for (const connector of [
    {
      id: process.env.META_ADS_CONNECTOR_ID ?? "meta-ads-live",
      kind: "META_ADS",
      externalAccountId: process.env.META_ADS_AD_ACCOUNT_ID,
      displayName: "Meta Ads – group-level read-only campaign insights",
      scopes: ["ads_read", "read_insights"],
    },
    {
      id: process.env.GOOGLE_ADS_CONNECTOR_ID ?? "google-ads-live",
      kind: "GOOGLE_ADS",
      externalAccountId: process.env.GOOGLE_ADS_CUSTOMER_ID,
      displayName: "Google Ads – group-level read-only campaign metrics",
      scopes: ["https://www.googleapis.com/auth/adwords", "account.read-only"],
    },
  ]) {
    if (!connector.externalAccountId) continue;
    await prisma.connectorAccount.upsert({
      where: { id: connector.id },
      create: {
        ...connector,
        organizationId,
        scope: "GROUP",
        scopeKey: "GROUP",
        status: "ACTIVE",
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
  const connectorId = process.env.WHATSAPP_CONNECTOR_ID ?? "whatsapp-live";
  await prisma.connectorAccount.upsert({
    where: { id: connectorId },
    create: {
      id: connectorId,
      organizationId,
      kind: "WHATSAPP_BUSINESS",
      scope: "GROUP",
      scopeKey: "GROUP",
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

console.log(
  `Connector seed completed for ${companies.length} legal entities ` +
    `(business mode: ${mode}).`,
);
await prisma.$disconnect();
