import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
try {
  const accounts = await prisma.connectorAccount.findMany({
    where: {
      kind: { in: ["BILLINGO", "META_ADS", "GOOGLE_ADS"] },
    },
    select: {
      id: true,
      kind: true,
      status: true,
      lastError: true,
      lastSuccessfulSyncAt: true,
    },
    orderBy: { kind: "asc" },
  });
  const events = await prisma.sourceEvent.findMany({
    where: {
      OR: [
        { labels: { has: "READ_ONLY_METRIC" } },
        { labels: { has: "BILLINGO" } },
      ],
    },
    select: { metadata: true },
  });
  const storedByProvider = {};
  for (const event of events) {
    const provider = String(event.metadata.provider ?? "UNKNOWN");
    storedByProvider[provider] = (storedByProvider[provider] ?? 0) + 1;
  }
  const expected = ["BILLINGO", "META_ADS", "GOOGLE_ADS"];
  const missingOrFailed = accounts.filter((account) => account.status !== "ACTIVE");
  const allProvidersStored = expected.every(
    (provider) => (storedByProvider[provider] ?? 0) > 0,
  );
  const ok =
    accounts.length === expected.length
    && missingOrFailed.length === 0
    && allProvidersStored;
  console.log(JSON.stringify({
    ok,
    accounts: accounts.map((account) => ({
      id: account.id,
      kind: account.kind,
      status: account.status,
      synced: Boolean(account.lastSuccessfulSyncAt),
      ...(account.lastError ? { error: account.lastError } : {}),
    })),
    storedByProvider,
  }));
  if (!ok) process.exitCode = 1;
} finally {
  await prisma.$disconnect();
}
