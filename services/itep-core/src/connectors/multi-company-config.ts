import { z } from "zod";
import { assertConnectorOwnership } from "./account-policy.js";
import type {
  ConnectorAccount,
  ConnectorKind,
  ConnectorScope,
  ConnectorStatus,
  LegalEntity,
} from "./types.js";

type SeedLegalEntity = Omit<LegalEntity, "createdAt" | "updatedAt">;
type SeedConnectorAccount = Omit<
  ConnectorAccount,
  "createdAt" | "updatedAt" | "lastSuccessfulSyncAt" | "lastError"
>;

const legalEntityInputSchema = z.object({
  id: z.string().min(1),
  slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  legalName: z.string().min(1),
  taxNumber: z.string().min(1).optional(),
  status: z.enum(["ACTIVE", "INACTIVE"]).default("ACTIVE"),
  metadata: z.record(z.unknown()).optional(),
});

const connectorInputSchema = z.object({
  id: z.string().min(1),
  kind: z.enum([
    "GMAIL",
    "CALENDAR",
    "DRIVE",
    "BILLINGO",
    "BANK",
    "CRM",
    "GOVERNMENT_PORTAL",
    "META_ADS",
    "GOOGLE_ADS",
  ]),
  scope: z.enum(["GROUP", "LEGAL_ENTITY"]),
  legalEntityId: z.string().min(1).optional(),
  externalAccountId: z.string().min(1),
  displayName: z.string().min(1),
  status: z.enum([
    "DISCONNECTED",
    "CONNECTING",
    "ACTIVE",
    "DEGRADED",
    "ERROR",
    "REAUTH_REQUIRED",
  ]).default("DISCONNECTED"),
  scopes: z.array(z.string().min(1)).default([]),
  configuration: z.record(z.unknown()).optional(),
});

export const IMPERIAL_LEGAL_ENTITY_SEEDS = [
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
] as const;

export function loadLegalEntitySeeds(
  organizationId: string,
  rawJson = process.env.LEGAL_ENTITIES_JSON,
): SeedLegalEntity[] {
  const defaults: SeedLegalEntity[] = IMPERIAL_LEGAL_ENTITY_SEEDS.map(
    ([slug, legalName]) => ({
    id: `${organizationId}:${slug}`,
    organizationId,
    slug,
    legalName,
    status: "ACTIVE" as const,
    metadata: {
      source: "initial-user-supplied-company-list",
      legalIdentifiersVerified: false,
    },
    }),
  );
  const additions = rawJson
    ? z.array(legalEntityInputSchema).parse(parseJson(rawJson, "LEGAL_ENTITIES_JSON"))
        .map((item) => ({ ...item, organizationId }))
    : [];
  return mergeById(defaults, additions);
}

export function buildPendingCompanyConnectors(
  entities: SeedLegalEntity[],
): SeedConnectorAccount[] {
  return entities.flatMap((entity) => [
    pendingConnector(entity, "BILLINGO", "Billingo", ["invoices.read"]),
    pendingConnector(entity, "BANK", "Bank", ["accounts.read", "transactions.read"]),
    pendingConnector(
      entity,
      "GOVERNMENT_PORTAL",
      "Cégkapu / hatósági tárhely",
      ["messages.read", "notifications.read"],
    ),
  ]);
}

export function loadAdditionalConnectorSeeds(
  organizationId: string,
  rawJson = process.env.BUSINESS_CONNECTOR_ACCOUNTS_JSON,
): SeedConnectorAccount[] {
  if (!rawJson) return [];
  return z.array(connectorInputSchema)
    .parse(parseJson(rawJson, "BUSINESS_CONNECTOR_ACCOUNTS_JSON"))
    .map((item) => {
      const scopeKey = item.scope === "GROUP"
        ? "GROUP"
        : item.legalEntityId ?? "";
      const connector = {
        ...item,
        organizationId,
        scopeKey,
      } as SeedConnectorAccount;
      assertConnectorOwnership(connector);
      return connector;
    });
}

export function groupConnector(input: {
  id: string;
  organizationId: string;
  kind: Extract<ConnectorKind, "CRM" | "META_ADS" | "GOOGLE_ADS">;
  externalAccountId: string;
  displayName: string;
  status: ConnectorStatus;
  scopes: string[];
  configuration?: Record<string, unknown>;
}): SeedConnectorAccount {
  const connector: SeedConnectorAccount = {
    ...input,
    scope: "GROUP",
    scopeKey: "GROUP",
  };
  assertConnectorOwnership(connector);
  return connector;
}

function pendingConnector(
  entity: SeedLegalEntity,
  kind: Extract<ConnectorKind, "BILLINGO" | "BANK" | "GOVERNMENT_PORTAL">,
  label: string,
  scopes: string[],
): SeedConnectorAccount {
  const id = `${kind.toLowerCase().replaceAll("_", "-")}-${entity.slug}`;
  const connector: SeedConnectorAccount = {
    id,
    organizationId: entity.organizationId,
    kind,
    scope: "LEGAL_ENTITY",
    scopeKey: entity.id,
    legalEntityId: entity.id,
    externalAccountId: "unconfigured",
    displayName: `${label} – ${entity.legalName}`,
    status: "DISCONNECTED",
    scopes,
    configuration: {
      credentialReference: id,
      provisioningState: "AWAITING_CREDENTIALS",
    },
  };
  assertConnectorOwnership(connector);
  return connector;
}

function parseJson(raw: string, name: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`${name} must contain valid JSON`);
  }
}

function mergeById<T extends { id: string }>(defaults: T[], additions: T[]): T[] {
  const merged = new Map(defaults.map((item) => [item.id, item]));
  for (const item of additions) merged.set(item.id, item);
  return [...merged.values()];
}

export type { SeedConnectorAccount, SeedLegalEntity };
