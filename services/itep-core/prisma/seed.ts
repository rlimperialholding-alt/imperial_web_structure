import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const now = new Date();
  const organizationId = process.env.DEFAULT_ORGANIZATION_ID ?? "imperial-holding";

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

  for (const manager of [
    { id: "digital-kalman", displayName: "Digitális Kálmán" },
    { id: "digital-mate", displayName: "Digitális Máté" },
    { id: "digital-misi", displayName: "Digitális Misi" },
  ]) {
    await prisma.digitalProjectManager.upsert({
      where: { id: manager.id },
      create: {
        ...manager,
        organizationId,
        roleName: "Digitális projektmenedzser",
        status: "ACTIVE",
      },
      update: {
        displayName: manager.displayName,
        roleName: "Digitális projektmenedzser",
        status: "ACTIVE",
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
