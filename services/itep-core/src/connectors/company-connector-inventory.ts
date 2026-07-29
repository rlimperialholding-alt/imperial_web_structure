import type { ConnectorAccount, LegalEntity } from "./types.js";

export interface CompanyConnectorInventoryReader {
  listByOrganization(organizationId: string): Promise<ConnectorAccount[]>;
}

export interface LegalEntityInventoryReader {
  listByOrganization(organizationId: string): Promise<LegalEntity[]>;
}

export class CompanyConnectorInventoryService {
  constructor(
    private readonly entities: LegalEntityInventoryReader,
    private readonly connectors: CompanyConnectorInventoryReader,
  ) {}

  async inspect(organizationId: string) {
    const [entities, connectors] = await Promise.all([
      this.entities.listByOrganization(organizationId),
      this.connectors.listByOrganization(organizationId),
    ]);
    const companyConnectors = new Map<string, ConnectorAccount[]>();
    const groupConnectors: ConnectorAccount[] = [];
    for (const connector of connectors) {
      if (connector.scope === "GROUP") {
        groupConnectors.push(connector);
        continue;
      }
      const key = connector.legalEntityId ?? "";
      companyConnectors.set(key, [
        ...(companyConnectors.get(key) ?? []),
        connector,
      ]);
    }

    return {
      organizationId,
      companies: entities.map((entity) => {
        const accounts = companyConnectors.get(entity.id) ?? [];
        return {
          id: entity.id,
          slug: entity.slug,
          legalName: entity.legalName,
          taxNumber: entity.taxNumber,
          status: entity.status,
          connectors: accounts.map(publicConnector),
          readiness: connectorReadiness(accounts),
        };
      }),
      groupConnectors: groupConnectors.map(publicConnector),
      totals: {
        companies: entities.length,
        activeCompanies: entities.filter((entity) => entity.status === "ACTIVE")
          .length,
        configuredCompanyConnectors: connectors.filter(
          (connector) =>
            connector.scope === "LEGAL_ENTITY" &&
            connector.status !== "DISCONNECTED",
        ).length,
        pendingCompanyConnectors: connectors.filter(
          (connector) =>
            connector.scope === "LEGAL_ENTITY" &&
            connector.status === "DISCONNECTED",
        ).length,
      },
    };
  }
}

function publicConnector(account: ConnectorAccount) {
  return {
    id: account.id,
    kind: account.kind,
    scope: account.scope,
    legalEntityId: account.legalEntityId,
    externalAccountId: account.externalAccountId,
    displayName: account.displayName,
    status: account.status,
    scopes: account.scopes,
    lastSuccessfulSyncAt: account.lastSuccessfulSyncAt,
    lastError: account.lastError,
  };
}

function connectorReadiness(accounts: ConnectorAccount[]) {
  const required = ["BILLINGO", "BANK", "GOVERNMENT_PORTAL"];
  return Object.fromEntries(required.map((kind) => {
    const account = accounts.find((item) => item.kind === kind);
    return [
      kind,
      {
        connectorId: account?.id,
        status: account?.status ?? "MISSING",
        configured: Boolean(
          account &&
          account.status !== "DISCONNECTED" &&
          account.externalAccountId !== "unconfigured"
        ),
      },
    ];
  }));
}
