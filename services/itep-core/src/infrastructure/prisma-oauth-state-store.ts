import type { PrismaClient } from "@prisma/client";
import type { OAuthStateStore } from "../connectors/oauth-service.js";

export class PrismaOAuthStateStore implements OAuthStateStore {
  constructor(private readonly prisma: PrismaClient) {}

  async save(input: Parameters<OAuthStateStore["save"]>[0]) {
    await this.prisma.oAuthState.create({
      data: {
        state: input.state,
        organizationId: input.organizationId,
        kind: input.kind,
        redirectUri: input.redirectUri,
        requestedScopes: input.requestedScopes,
        createdBy: input.createdBy,
        expiresAt: input.expiresAt,
      },
    });
  }

  async consume(state: string) {
    return this.prisma.$transaction(async (tx) => {
      const row = await tx.oAuthState.findUnique({ where: { state } });
      if (!row || row.consumedAt || row.expiresAt <= new Date()) return null;

      await tx.oAuthState.update({
        where: { state },
        data: { consumedAt: new Date() },
      });

      return {
        organizationId: row.organizationId,
        kind: row.kind,
        redirectUri: row.redirectUri,
        requestedScopes: row.requestedScopes,
        createdBy: row.createdBy,
      };
    });
  }
}
