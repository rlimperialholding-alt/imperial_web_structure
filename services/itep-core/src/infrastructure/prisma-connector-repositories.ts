import type { Prisma, PrismaClient } from "@prisma/client";
import type {
  ConnectorAccountRepository,
  SyncCheckpointRepository,
} from "../connectors/ports.js";
import type {
  ConnectorAccount,
  LegalEntity,
  SyncCheckpoint,
} from "../connectors/types.js";

export class PrismaConnectorAccountRepository
  implements ConnectorAccountRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async getById(id: string): Promise<ConnectorAccount | null> {
    const row = await this.prisma.connectorAccount.findUnique({
      where: { id },
    });
    return row ? mapAccount(row) : null;
  }

  async save(account: ConnectorAccount): Promise<void> {
    await this.prisma.connectorAccount.upsert({
      where: { id: account.id },
      create: {
        id: account.id,
        organizationId: account.organizationId,
        kind: account.kind,
        scope: account.scope,
        scopeKey: account.scopeKey,
        legalEntityId: account.legalEntityId ?? null,
        externalAccountId: account.externalAccountId,
        displayName: account.displayName,
        status: account.status,
        scopes: account.scopes,
        configuration:
          account.configuration as Prisma.InputJsonValue | undefined,
        createdAt: account.createdAt,
        updatedAt: account.updatedAt,
        lastSuccessfulSyncAt: account.lastSuccessfulSyncAt ?? null,
        lastError: account.lastError ?? null,
      },
      update: {
        displayName: account.displayName,
        status: account.status,
        scopes: account.scopes,
        scope: account.scope,
        scopeKey: account.scopeKey,
        legalEntityId: account.legalEntityId ?? null,
        configuration:
          account.configuration as Prisma.InputJsonValue | undefined,
        updatedAt: account.updatedAt,
        lastSuccessfulSyncAt: account.lastSuccessfulSyncAt ?? null,
        lastError: account.lastError ?? null,
      },
    });
  }

  async listActive(kind?: string): Promise<ConnectorAccount[]> {
    const rows = await this.prisma.connectorAccount.findMany({
      where: {
        status: { in: ["ACTIVE", "DEGRADED"] },
        ...(kind ? { kind: kind as any } : {}),
      },
      orderBy: { updatedAt: "asc" },
    });
    return rows.map(mapAccount);
  }

  async listByOrganization(organizationId: string): Promise<ConnectorAccount[]> {
    const rows = await this.prisma.connectorAccount.findMany({
      where: { organizationId },
      orderBy: [{ kind: "asc" }, { displayName: "asc" }],
    });
    return rows.map(mapAccount);
  }
}

export class PrismaLegalEntityRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async listByOrganization(organizationId: string): Promise<LegalEntity[]> {
    const rows = await this.prisma.legalEntity.findMany({
      where: { organizationId },
      orderBy: { legalName: "asc" },
    });
    return rows.map((row) => ({
      id: row.id,
      organizationId: row.organizationId,
      slug: row.slug,
      legalName: row.legalName,
      ...(row.taxNumber ? { taxNumber: row.taxNumber } : {}),
      status: row.status,
      ...(row.metadata && typeof row.metadata === "object"
        ? { metadata: row.metadata as Record<string, unknown> }
        : {}),
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
    }));
  }
}

export class PrismaSyncCheckpointRepository
  implements SyncCheckpointRepository {
  constructor(private readonly prisma: PrismaClient) {}

  async get(connectorAccountId: string): Promise<SyncCheckpoint | null> {
    const row = await this.prisma.syncCheckpoint.findUnique({
      where: { connectorAccountId },
    });
    return row ? {
      id: row.id,
      connectorAccountId: row.connectorAccountId,
      ...(row.cursor ? { cursor: row.cursor } : {}),
      ...(row.historyId ? { historyId: row.historyId } : {}),
      ...(row.syncToken ? { syncToken: row.syncToken } : {}),
      ...(row.expiresAt ? { expiresAt: row.expiresAt } : {}),
      updatedAt: row.updatedAt,
    } : null;
  }

  async save(checkpoint: SyncCheckpoint): Promise<void> {
    await this.prisma.syncCheckpoint.upsert({
      where: { connectorAccountId: checkpoint.connectorAccountId },
      create: {
        id: checkpoint.id,
        connectorAccountId: checkpoint.connectorAccountId,
        cursor: checkpoint.cursor ?? null,
        historyId: checkpoint.historyId ?? null,
        syncToken: checkpoint.syncToken ?? null,
        expiresAt: checkpoint.expiresAt ?? null,
        updatedAt: checkpoint.updatedAt,
      },
      update: {
        cursor: checkpoint.cursor ?? null,
        historyId: checkpoint.historyId ?? null,
        syncToken: checkpoint.syncToken ?? null,
        expiresAt: checkpoint.expiresAt ?? null,
        updatedAt: checkpoint.updatedAt,
      },
    });
  }
}

function mapAccount(row: any): ConnectorAccount {
  return {
    id: row.id,
    organizationId: row.organizationId,
    kind: row.kind,
    scope: row.scope,
    scopeKey: row.scopeKey,
    ...(row.legalEntityId ? { legalEntityId: row.legalEntityId } : {}),
    externalAccountId: row.externalAccountId,
    displayName: row.displayName,
    status: row.status,
    scopes: row.scopes,
    ...(row.configuration && typeof row.configuration === "object"
      ? { configuration: row.configuration }
      : {}),
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
    ...(row.lastSuccessfulSyncAt
      ? { lastSuccessfulSyncAt: row.lastSuccessfulSyncAt }
      : {}),
    ...(row.lastError ? { lastError: row.lastError } : {}),
  };
}
