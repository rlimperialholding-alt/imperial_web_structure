import { PrismaClient } from "@prisma/client";
import {
  buildPendingCompanyConnectors,
  groupConnector,
  loadAdditionalConnectorSeeds,
  loadLegalEntitySeeds,
  type SeedConnectorAccount,
} from "../src/connectors/multi-company-config.js";

const prisma = new PrismaClient();

async function main() {
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
  const entities = loadLegalEntitySeeds(organizationId);

  for (const entity of entities) {
    await prisma.legalEntity.upsert({
      where: { id: entity.id },
      create: entity,
      update: {
        slug: entity.slug,
        legalName: entity.legalName,
        taxNumber: entity.taxNumber ?? null,
        status: entity.status,
        metadata: entity.metadata,
      },
    });
  }

  const connectors = mergeConnectors(
    buildPendingCompanyConnectors(entities),
    loadAdditionalConnectorSeeds(organizationId),
    configuredGroupConnectors(organizationId),
    configuredBillingoConnector(organizationId),
    configuredWhatsAppConnector(organizationId),
  );

  for (const connector of connectors) {
    await prisma.connectorAccount.upsert({
      where: { id: connector.id },
      create: connector,
      update: {
        organizationId: connector.organizationId,
        kind: connector.kind,
        scope: connector.scope,
        scopeKey: connector.scopeKey,
        legalEntityId: connector.legalEntityId ?? null,
        externalAccountId: connector.externalAccountId,
        displayName: connector.displayName,
        status: connector.status,
        scopes: connector.scopes,
        configuration: connector.configuration,
        lastError: null,
      },
    });
  }

  console.log(
    `Seed completed: ${entities.length} legal entities, ` +
      `${connectors.length} connector accounts.`,
  );
}

function configuredGroupConnectors(
  organizationId: string,
): SeedConnectorAccount[] {
  const connectors: SeedConnectorAccount[] = [{
    id: "connector-demo-gmail",
    organizationId,
    kind: "GMAIL",
    scope: "GROUP",
    scopeKey: "GROUP",
    externalAccountId: "office@example.invalid",
    displayName: "Demo Gmail connector",
    status: "DISCONNECTED",
    scopes: ["gmail.readonly"],
  }];
  const crmWorkspaceId = process.env.CRM_WORKSPACE_ID;
  if (crmWorkspaceId) {
    connectors.push(groupConnector({
      id: process.env.ITEP_CRM_CONNECTOR_ID ?? "crm-live",
      organizationId,
      kind: "CRM",
      externalAccountId: crmWorkspaceId,
      displayName: "Imperial Sales CRM – internal read-only",
      status: "ACTIVE",
      scopes: ["activities.read", "leads.read", "deals.read"],
    }));
  }

  if ((process.env.BUSINESS_CONNECTORS_MODE ?? "disabled") !== "read-only") {
    return connectors;
  }

  if (process.env.META_ADS_AD_ACCOUNT_ID) {
    connectors.push(groupConnector({
      id: process.env.META_ADS_CONNECTOR_ID ?? "meta-ads-live",
      organizationId,
      kind: "META_ADS",
      externalAccountId: process.env.META_ADS_AD_ACCOUNT_ID,
      displayName: "Meta Ads – group-level read-only campaign insights",
      status: "ACTIVE",
      scopes: ["ads_read", "read_insights"],
    }));
  }
  if (process.env.GOOGLE_ADS_CUSTOMER_ID) {
    connectors.push(groupConnector({
      id: process.env.GOOGLE_ADS_CONNECTOR_ID ?? "google-ads-live",
      organizationId,
      kind: "GOOGLE_ADS",
      externalAccountId: process.env.GOOGLE_ADS_CUSTOMER_ID,
      displayName: "Google Ads – group-level read-only campaign metrics",
      status: "ACTIVE",
      scopes: [
        "https://www.googleapis.com/auth/adwords",
        "account.read-only",
      ],
    }));
  }
  return connectors;
}

function configuredBillingoConnector(
  organizationId: string,
): SeedConnectorAccount[] {
  if ((process.env.BUSINESS_CONNECTORS_MODE ?? "disabled") !== "read-only") {
    return [];
  }
  const legalEntityId = process.env.BILLINGO_LEGAL_ENTITY_ID;
  if (!legalEntityId) return [];
  const slug = legalEntityId.split(":").at(-1) ?? legalEntityId;
  return [{
    id: process.env.BILLINGO_CONNECTOR_ID ?? `billingo-${slug}`,
    organizationId,
    kind: "BILLINGO",
    scope: "LEGAL_ENTITY",
    scopeKey: legalEntityId,
    legalEntityId,
    externalAccountId: process.env.BILLINGO_EXTERNAL_ACCOUNT_ID ?? "all",
    displayName: `Billingo – ${slug}`,
    status: "ACTIVE",
    scopes: ["invoices.read"],
    configuration: {
      credentialReference:
        process.env.BILLINGO_CONNECTOR_ID ?? `billingo-${slug}`,
    },
  }];
}

function configuredWhatsAppConnector(
  organizationId: string,
): SeedConnectorAccount[] {
  const phoneNumberId = process.env.WHATSAPP_PHONE_NUMBER_ID;
  if (!phoneNumberId) return [];
  return [groupConnector({
    id: process.env.WHATSAPP_CONNECTOR_ID ?? "whatsapp-live",
    organizationId,
    kind: "WHATSAPP_BUSINESS",
    externalAccountId: phoneNumberId,
    displayName: "WhatsApp Business – CRM customer service",
    status: "ACTIVE",
    scopes: [
      "whatsapp_business_management",
      "whatsapp_business_messaging",
    ],
  })];
}

function mergeConnectors(
  ...groups: SeedConnectorAccount[][]
): SeedConnectorAccount[] {
  const merged = new Map<string, SeedConnectorAccount>();
  for (const group of groups) {
    for (const connector of group) merged.set(connector.id, connector);
  }
  return [...merged.values()];
}

main()
  .catch((error) => {
    console.error(error);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
