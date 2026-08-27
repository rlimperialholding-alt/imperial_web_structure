import type {
  ConnectorAccount,
  ConnectorKind,
  ConnectorScope,
} from "./types.js";

const LEGAL_ENTITY_KINDS = new Set<ConnectorKind>([
  "BILLINGO",
  "BANK",
  "GOVERNMENT_PORTAL",
]);
const GROUP_KINDS = new Set<ConnectorKind>(["META_ADS", "GOOGLE_ADS"]);

export function requiredConnectorScope(
  kind: ConnectorKind,
): ConnectorScope | undefined {
  if (LEGAL_ENTITY_KINDS.has(kind)) return "LEGAL_ENTITY";
  if (GROUP_KINDS.has(kind)) return "GROUP";
  return undefined;
}

export function assertConnectorOwnership(
  account: Pick<
    ConnectorAccount,
    "id" | "kind" | "scope" | "scopeKey" | "legalEntityId"
  >,
): void {
  const required = requiredConnectorScope(account.kind);
  if (required && account.scope !== required) {
    throw new Error(
      `${account.kind} connector ${account.id} must use ${required} scope`,
    );
  }
  if (account.scope === "GROUP") {
    if (account.legalEntityId || account.scopeKey !== "GROUP") {
      throw new Error(
        `Group connector ${account.id} cannot reference a legal entity`,
      );
    }
    return;
  }
  if (!account.legalEntityId || account.scopeKey !== account.legalEntityId) {
    throw new Error(
      `Legal-entity connector ${account.id} requires matching legalEntityId and scopeKey`,
    );
  }
}
