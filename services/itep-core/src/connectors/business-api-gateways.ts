import type { CrmActivityEvent } from "./business-event-normalizers.js";
import type { BillingoGateway } from "./billingo-sync-adapter.js";
import type { BankGateway } from "./bank-sync-adapter.js";
import type { CrmGateway } from "./crm-sync-adapter.js";
type FetchLike=(input:string,init?:RequestInit)=>Promise<Response>;

export class BillingoApiGateway implements BillingoGateway {
  constructor(private readonly baseUrl:string,
    private readonly fetcher:FetchLike=fetch){}
  async listInvoiceChanges(input:{accessToken:string;externalAccountId:string;cursor?:string}){
    const url=new URL("/v3/documents",this.baseUrl);
    url.searchParams.set("per_page", "100");
    if (!["all", "account"].includes(input.externalAccountId.toLowerCase())) {
      url.searchParams.set("partner_id",input.externalAccountId);
    }
    if(input.cursor)url.searchParams.set("page",input.cursor);
    const response=await this.fetcher(url.toString(),{
      headers:{"X-API-KEY":input.accessToken,Accept:"application/json"}});
    await assertSuccess(response,"Billingo"); const p:any=await response.json();
    const invoices=(p.data??p.invoices??[]).map((x:any)=>({
      invoiceId:String(x.id),invoiceNumber:String(x.invoice_number??x.id),
      projectId:str(x.project_id),customerName:String(x.partner?.name??"Ismeretlen ügyfél"),
      customerEmail:str(x.partner?.emails?.[0]),
      status:String(x.cancelled ? "CANCELLED" : x.payment_status??x.status??"UNKNOWN"),
      grossAmount:Number(x.gross_total??0),currency:String(x.currency??"HUF"),
      dueAt:date(x.due_date),paidAt:date(x.paid_date??x.paid_at),
      updatedAt:date(x.updated_at??x.invoice_date??x.due_date)??new Date()}));
    const current=Number(p.current_page??input.cursor??1),last=Number(p.last_page??current);
    return {invoices,...(current<last?{nextCursor:String(current+1)}:{})};
  }
}
export class Psd2BankApiGateway implements BankGateway {
  constructor(private readonly baseUrl:string,
    private readonly fetcher:FetchLike=fetch){}
  async listTransactionChanges(input:{accessToken:string;externalAccountId:string;cursor?:string}){
    const url=new URL(`/accounts/${encodeURIComponent(input.externalAccountId)}/transactions`,this.baseUrl);
    if(input.cursor)url.searchParams.set("cursor",input.cursor);
    const response=await this.fetcher(url.toString(),{
      headers:{Authorization:`Bearer ${input.accessToken}`,Accept:"application/json"}});
    await assertSuccess(response,"Bank"); const p:any=await response.json();
    const source=p.transactions?.booked??p.transactions??p.data??[];
    const transactions=source.map((x:any)=>{const a=x.transactionAmount??x.amount??{};
      return {transactionId:String(x.transactionId??x.entryReference??x.id),
        accountId:input.externalAccountId,projectId:str(x.projectId),
        bookingDate:date(x.bookingDate??x.bookingDateTime)??new Date(),
        amount:Number(a.amount??x.amount_value??0),currency:String(a.currency??x.currency??"HUF"),
        counterpartyName:str(x.creditorName??x.debtorName),
        counterpartyAccount:str(x.creditorAccount?.iban??x.debtorAccount?.iban),
        remittanceInformation:str(x.remittanceInformationUnstructured??x.description),
        status:String(x.status??"BOOKED")};});
    return {transactions,...(p.nextCursor?{nextCursor:String(p.nextCursor)}:{})};
  }
}

export interface GenericCrmApiOptions {
  activitiesPath?: string;
  authHeader?: string;
  authScheme?: string;
  workspaceQueryParameter?: string;
}

export class GenericCrmApiGateway implements CrmGateway {
  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: FetchLike = fetch,
    private readonly options: GenericCrmApiOptions = {},
  ) {}

  async listActivityChanges(input: {
    accessToken: string;
    externalAccountId: string;
    cursor?: string;
  }) {
    const url = new URL(
      this.options.activitiesPath ?? "/api/v1/activities",
      this.baseUrl,
    );
    url.searchParams.set(
      this.options.workspaceQueryParameter ?? "workspace",
      input.externalAccountId,
    );
    if (input.cursor) url.searchParams.set("cursor", input.cursor);

    const authHeader = this.options.authHeader ?? "Authorization";
    const authScheme = this.options.authScheme ?? "Bearer";
    const authValue = authScheme
      ? `${authScheme} ${input.accessToken}`
      : input.accessToken;

    const response = await this.fetcher(url.toString(), {
      headers: {
        [authHeader]: authValue,
        Accept: "application/json",
      },
    });
    await assertSuccess(response, "CRM");

    const payload = (await response.json()) as any;
    const activities: CrmActivityEvent[] = (
      payload.activities ?? payload.items ?? payload.data ?? []
    ).map((item: any) => ({
      activityId: String(item.id ?? item.activityId ?? item.activity_id),
      projectId: optionalString(item.projectId ?? item.project_id),
      leadId: optionalString(item.leadId ?? item.lead_id),
      dealId: optionalString(item.dealId ?? item.deal_id),
      type: String(item.type ?? item.activity_type ?? "TASK"),
      title: String(item.title ?? item.subject ?? "CRM feladat"),
      description: optionalString(item.description ?? item.body ?? item.notes),
      ownerId: optionalString(item.ownerId ?? item.owner_id),
      ownerEmail: optionalString(item.ownerEmail ?? item.owner_email),
      contactEmail: optionalString(item.contactEmail ?? item.contact_email),
      dueAt: optionalDate(item.dueAt ?? item.due_at ?? item.deadline),
      occurredAt:
        optionalDate(
          item.updatedAt ??
          item.updated_at ??
          item.createdAt ??
          item.created_at
        ) ?? new Date(),
      status: String(item.status ?? "OPEN"),
      priority: optionalString(item.priority),
    }));

    return {
      activities,
      ...(payload.nextCursor ?? payload.next_cursor ?? payload.pagination?.next
        ? {
            nextCursor: String(
              payload.nextCursor ??
              payload.next_cursor ??
              payload.pagination?.next
            ),
          }
        : {}),
    };
  }
}

async function assertSuccess(r:Response,p:string){if(r.ok)return;
  throw new Error(`${p} API ${r.status}: ${(await r.text()).slice(0,500)}`);}
function optionalString(value: unknown): string | undefined {
  return value === undefined || value === null || value === ""
    ? undefined
    : String(value);
}
function optionalDate(value: unknown): Date | undefined {
  if (!value) return undefined;
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? undefined : parsed;
}
const str = optionalString;
const date = optionalDate;
