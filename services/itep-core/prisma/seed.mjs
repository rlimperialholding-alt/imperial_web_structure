// Plain-Node compatibility seed used by the integrated repository validator.
// The canonical seed command is `npm run seed` (prisma/seed.ts).
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
const organizationId =
  process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding";
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
    "Imperial Holding Mérnöki és Tanácsadó Kft.",
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

console.log(`Connector seed completed for ${companies.length} legal entities.`);
await prisma.$disconnect();
