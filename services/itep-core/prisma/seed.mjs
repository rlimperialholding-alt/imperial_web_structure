import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
const workspaceId = process.env.CRM_WORKSPACE_ID;
if (!workspaceId) {
  throw new Error("CRM_WORKSPACE_ID is required for the GitHub test environment");
}
await prisma.connectorAccount.upsert({
  where: {
    organizationId_kind_externalAccountId: {
      organizationId: process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding",
      kind: "CRM",
      externalAccountId: workspaceId,
    },
  },
  create: {
    id: process.env.ITEP_CRM_CONNECTOR_ID ?? "crm-live",
    organizationId: process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding",
    kind: "CRM",
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

console.log("Internal CRM connector seeded.");
await prisma.$disconnect();
