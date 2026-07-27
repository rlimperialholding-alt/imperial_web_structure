import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { ConnectorSyncOrchestrator } from "../connectors/sync-orchestrator.js";
import type { CompanyConnectorInventoryService } from "../connectors/company-connector-inventory.js";
import { actorFromRequest } from "./actor-context.js";

const kindSchema = z.object({
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
  ]).optional(),
});

export function registerConnectorRoutes(
  app: FastifyInstance,
  orchestrator: ConnectorSyncOrchestrator,
  inventory?: CompanyConnectorInventoryService,
): void {
  if (inventory) {
    app.get("/v1/companies/connectors", async (request) => {
      const actor = actorFromRequest(request);
      return inventory.inspect(actor.organizationId);
    });
  }

  app.post<{ Params: { id: string } }>(
    "/v1/connectors/:id/sync",
    async (request) => {
      actorFromRequest(request);
      return orchestrator.syncAccount(request.params.id);
    },
  );

  app.post("/internal/connectors/sync-all", async (request) => {
    actorFromRequest(request);
    const { kind } = kindSchema.parse(request.query);
    return orchestrator.syncAll(kind);
  });
}
