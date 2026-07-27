import { describe, expect, it } from "vitest";
import {
  assertConnectorOwnership,
  requiredConnectorScope,
} from "../src/connectors/account-policy.js";
import { CompanyConnectorInventoryService } from "../src/connectors/company-connector-inventory.js";
import {
  buildPendingCompanyConnectors,
  loadAdditionalConnectorSeeds,
  loadLegalEntitySeeds,
} from "../src/connectors/multi-company-config.js";

describe("multi-company connector ownership", () => {
  it("seeds the supplied companies and three isolated connector slots each", () => {
    const entities = loadLegalEntitySeeds("imperial-holding");
    const connectors = buildPendingCompanyConnectors(entities);
    expect(entities).toHaveLength(12);
    expect(connectors).toHaveLength(36);
    expect(new Set(connectors.map((item) => item.scopeKey)).size).toBe(12);
    expect(connectors.every((item) => item.scope === "LEGAL_ENTITY")).toBe(true);
  });

  it("allows future companies and connectors through JSON configuration", () => {
    const entities = loadLegalEntitySeeds(
      "imperial-holding",
      JSON.stringify([{
        id: "imperial-holding:new-company",
        slug: "new-company",
        legalName: "New Company Kft.",
      }]),
    );
    const connectors = loadAdditionalConnectorSeeds(
      "imperial-holding",
      JSON.stringify([{
        id: "billingo-new-company",
        kind: "BILLINGO",
        scope: "LEGAL_ENTITY",
        legalEntityId: "imperial-holding:new-company",
        externalAccountId: "all",
        displayName: "Billingo – New Company Kft.",
        status: "ACTIVE",
        scopes: ["invoices.read"],
      }]),
    );
    expect(entities.some((item) => item.slug === "new-company")).toBe(true);
    expect(connectors[0]?.scopeKey).toBe("imperial-holding:new-company");
  });

  it("enforces company ownership for finance and group ownership for ads", () => {
    expect(requiredConnectorScope("BILLINGO")).toBe("LEGAL_ENTITY");
    expect(requiredConnectorScope("BANK")).toBe("LEGAL_ENTITY");
    expect(requiredConnectorScope("GOVERNMENT_PORTAL")).toBe("LEGAL_ENTITY");
    expect(requiredConnectorScope("META_ADS")).toBe("GROUP");
    expect(requiredConnectorScope("GOOGLE_ADS")).toBe("GROUP");
    expect(() => assertConnectorOwnership({
      id: "bad-billingo",
      kind: "BILLINGO",
      scope: "GROUP",
      scopeKey: "GROUP",
    })).toThrow("must use LEGAL_ENTITY");
  });

  it("reports per-company readiness without exposing credential data", async () => {
    const entities = loadLegalEntitySeeds("imperial-holding").slice(0, 1);
    const connectors = buildPendingCompanyConnectors(entities);
    const inventory = new CompanyConnectorInventoryService(
      { async listByOrganization() {
        return entities.map((entity) => ({
          ...entity,
          createdAt: new Date(),
          updatedAt: new Date(),
        }));
      } },
      { async listByOrganization() {
        return connectors.map((connector) => ({
          ...connector,
          createdAt: new Date(),
          updatedAt: new Date(),
        }));
      } },
    );
    const result = await inventory.inspect("imperial-holding");
    expect(result.companies[0]?.readiness.BILLINGO.configured).toBe(false);
    expect(JSON.stringify(result)).not.toContain("accessToken");
    expect(JSON.stringify(result)).not.toContain("credentialReference");
  });
});
