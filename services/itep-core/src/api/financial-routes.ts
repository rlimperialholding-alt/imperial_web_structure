import type { Prisma, PrismaClient } from "@prisma/client";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { actorFromRequest } from "./actor-context.js";

const incomingInvoiceQuery = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(10).max(100).default(50),
  search: z.string().trim().max(120).optional(),
  paymentStatus: z.enum(["PAID", "UNPAID"]).optional(),
  currency: z.string().trim().min(3).max(3).optional(),
});

type InvoiceMetadata = {
  invoiceNumber?: string;
  issueDate?: string;
  fulfillmentDate?: string | null;
  dueDate?: string | null;
  paymentDate?: string | null;
  paymentMethod?: string;
  netAmount?: number;
  vatAmount?: number;
  grossAmount?: number;
  currency?: string;
  partnerName?: string;
  taxNumber?: string;
  category?: string;
  note?: string;
  sourceRowHash?: string;
};

export function registerFinancialRoutes(
  app: FastifyInstance,
  prisma: PrismaClient,
): void {
  app.get("/v1/financial/incoming-invoices", async (request) => {
    const actor = actorFromRequest(request);
    if (!actor.permissions.includes("financial:read")) {
      throw new Error("financial:read permission required");
    }
    const query = incomingInvoiceQuery.parse(request.query);
    const conditions: Prisma.SourceEventWhereInput[] = [
      {
        organizationId: actor.organizationId,
        source: "WEBHOOK",
        labels: { hasEvery: ["BILLINGO", "INCOMING_INVOICE"] },
      },
    ];
    if (query.paymentStatus) {
      conditions.push({ labels: { has: query.paymentStatus } });
    }
    if (query.currency) {
      conditions.push({
        metadata: {
          path: ["currency"],
          equals: query.currency.toUpperCase(),
        },
      });
    }
    if (query.search) {
      conditions.push({
        OR: [
          {
            subject: {
              contains: query.search,
              mode: "insensitive",
            },
          },
          {
            body: {
              contains: query.search,
              mode: "insensitive",
            },
          },
        ],
      });
    }
    const where: Prisma.SourceEventWhereInput = { AND: conditions };
    const offset = (query.page - 1) * query.pageSize;
    const [rows, summaryRows] = await Promise.all([
      prisma.sourceEvent.findMany({
        where,
        orderBy: [{ occurredAt: "desc" }, { id: "desc" }],
        skip: offset,
        take: query.pageSize,
        select: {
          id: true,
          occurredAt: true,
          labels: true,
          metadata: true,
        },
      }),
      prisma.sourceEvent.findMany({
        where,
        select: {
          labels: true,
          metadata: true,
        },
      }),
    ]);

    const currencyTotals: Record<
      string,
      { count: number; grossAmount: number }
    > = {};
    let paid = 0;
    for (const row of summaryRows) {
      const metadata = row.metadata as InvoiceMetadata;
      if (row.labels.includes("PAID")) paid += 1;
      const currency = metadata.currency ?? "UNKNOWN";
      const current = currencyTotals[currency] ?? {
        count: 0,
        grossAmount: 0,
      };
      current.count += 1;
      current.grossAmount += Number(metadata.grossAmount ?? 0);
      currencyTotals[currency] = current;
    }

    return {
      page: query.page,
      pageSize: query.pageSize,
      total: summaryRows.length,
      totalPages: Math.max(1, Math.ceil(summaryRows.length / query.pageSize)),
      filters: {
        search: query.search ?? "",
        paymentStatus: query.paymentStatus ?? "",
        currency: query.currency?.toUpperCase() ?? "",
      },
      summary: {
        paid,
        unpaid: summaryRows.length - paid,
        currencyTotals,
      },
      items: rows.map((row) => {
        const metadata = row.metadata as InvoiceMetadata;
        return {
          id: row.id,
          invoiceNumber: metadata.invoiceNumber ?? "",
          partnerName: metadata.partnerName ?? "",
          taxNumber: metadata.taxNumber ?? "",
          category: metadata.category ?? "",
          paymentMethod: metadata.paymentMethod ?? "",
          issueDate:
            metadata.issueDate ?? row.occurredAt.toISOString().slice(0, 10),
          fulfillmentDate: metadata.fulfillmentDate ?? null,
          dueDate: metadata.dueDate ?? null,
          paymentDate: metadata.paymentDate ?? null,
          netAmount: Number(metadata.netAmount ?? 0),
          vatAmount: Number(metadata.vatAmount ?? 0),
          grossAmount: Number(metadata.grossAmount ?? 0),
          currency: metadata.currency ?? "",
          note: metadata.note ?? "",
          paymentStatus: row.labels.includes("PAID") ? "PAID" : "UNPAID",
          sourceRowHash: metadata.sourceRowHash ?? "",
        };
      }),
    };
  });
}
