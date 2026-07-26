import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

async function main() {
  const now = new Date();
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
