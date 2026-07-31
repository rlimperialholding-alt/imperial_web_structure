import { and, asc, eq, gte, lte } from "drizzle-orm";
import { getDb } from "@/db";
import { businessAuditEvents, cashflowEntries, projects } from "@/db/schema";
import { jsonError, requireInternalCrmIdentity, type CrmIdentity } from "@/lib/crm-auth";

function canReadFinance(identity: CrmIdentity) {
  return identity.role === "admin" || identity.permissions.includes("*")
    || identity.permissions.some((permission) => ["finance.read", "finance.write"].includes(permission));
}

function canWriteFinance(identity: CrmIdentity) {
  return identity.role === "admin" || identity.permissions.includes("*")
    || identity.permissions.includes("finance.write");
}

function validDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value);
}

export async function GET(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    if (!canReadFinance(identity)) return Response.json({ error: "Nincs pénzügyi olvasási jogosultságod." }, { status: 403 });
    const url = new URL(request.url);
    const year = new Date().getUTCFullYear();
    const from = url.searchParams.get("from") || `${year}-01-01`;
    const to = url.searchParams.get("to") || `${year}-12-31`;
    if (!validDate(from) || !validDate(to) || from > to) {
      return Response.json({ error: "Érvénytelen cashflow-időszak." }, { status: 400 });
    }
    const db = await getDb();
    const entries = await db.select().from(cashflowEntries).where(and(
      gte(cashflowEntries.dueDate, from),
      lte(cashflowEntries.dueDate, to),
    )).orderBy(asc(cashflowEntries.dueDate));
    const today = new Date().toISOString().slice(0, 10);
    const byCurrency = new Map<string, {
      currency: string;
      actualInflow: number;
      actualOutflow: number;
      forecastInflow: number;
      forecastOutflow: number;
      overdueOutflow: number;
    }>();
    const monthly = new Map<string, {
      month: string;
      currency: string;
      actualInflow: number;
      actualOutflow: number;
      forecastInflow: number;
      forecastOutflow: number;
    }>();
    for (const entry of entries) {
      if (entry.status === "cancelled") continue;
      const currency = byCurrency.get(entry.currency) ?? {
        currency: entry.currency,
        actualInflow: 0,
        actualOutflow: 0,
        forecastInflow: 0,
        forecastOutflow: 0,
        overdueOutflow: 0,
      };
      const monthKey = `${entry.dueDate.slice(0, 7)}:${entry.currency}`;
      const month = monthly.get(monthKey) ?? {
        month: entry.dueDate.slice(0, 7),
        currency: entry.currency,
        actualInflow: 0,
        actualOutflow: 0,
        forecastInflow: 0,
        forecastOutflow: 0,
      };
      const direction = entry.direction === "inflow" ? "Inflow" : "Outflow";
      if (entry.status === "paid") {
        currency[`actual${direction}`] += entry.amount;
        month[`actual${direction}`] += entry.amount;
      } else {
        currency[`forecast${direction}`] += entry.amount;
        month[`forecast${direction}`] += entry.amount;
        if (entry.direction === "outflow" && entry.status === "due" && entry.dueDate < today) {
          currency.overdueOutflow += entry.amount;
        }
      }
      byCurrency.set(entry.currency, currency);
      monthly.set(monthKey, month);
    }
    return Response.json({
      period: { from, to },
      summaries: Array.from(byCurrency.values()).map((item) => ({
        ...item,
        actualBalance: item.actualInflow - item.actualOutflow,
        forecastBalance: item.forecastInflow - item.forecastOutflow,
      })),
      monthly: Array.from(monthly.values()).sort((a, b) => `${a.month}:${a.currency}`.localeCompare(`${b.month}:${b.currency}`)),
      entries,
    });
  } catch (error) { return jsonError(error); }
}

export async function POST(request: Request) {
  try {
    const identity = await requireInternalCrmIdentity(request);
    if (!canWriteFinance(identity)) return Response.json({ error: "Nincs pénzügyi írási jogosultságod." }, { status: 403 });
    const body = await request.json() as Record<string, unknown>;
    const direction = body.direction === "inflow" ? "inflow" : body.direction === "outflow" ? "outflow" : null;
    const status = body.status === "due" ? "due" : "planned";
    const amount = Math.round(Number(body.amount ?? 0));
    const dueDate = String(body.dueDate ?? "").trim();
    const category = String(body.category ?? "").trim();
    const counterparty = String(body.counterparty ?? "").trim();
    const description = String(body.description ?? "").trim();
    const projectId = String(body.projectId ?? "").trim() || null;
    if (!direction || !Number.isSafeInteger(amount) || amount <= 0 || !validDate(dueDate) || !category || !counterparty || !description) {
      return Response.json({ error: "Az irány, pozitív összeg, dátum, kategória, partner és leírás kötelező." }, { status: 400 });
    }
    const db = await getDb();
    if (projectId && !(await db.select({ id: projects.id }).from(projects).where(eq(projects.id, projectId)).limit(1))[0]) {
      return Response.json({ error: "A projekt nem található." }, { status: 404 });
    }
    const now = new Date().toISOString();
    const entry = {
      id: `CF-${crypto.randomUUID().toUpperCase()}`,
      sourceType: "manual" as const,
      sourceId: null,
      direction,
      category,
      counterparty,
      description,
      projectId,
      amount,
      currency: String(body.currency ?? "HUF").trim().toUpperCase(),
      status,
      dueDate,
      paidAt: null,
      createdByEmail: identity.email,
      createdAt: now,
      updatedAt: now,
    };
    await db.batch([
      db.insert(cashflowEntries).values(entry),
      db.insert(businessAuditEvents).values({
        actorEmail: identity.email,
        action: "cashflow.created",
        entityType: "cashflow_entry",
        entityId: entry.id,
        detail: `${entry.direction} · ${entry.amount} ${entry.currency} · ${entry.counterparty}`,
        createdAt: now,
      }),
    ]);
    return Response.json({ entry }, { status: 201 });
  } catch (error) { return jsonError(error); }
}
