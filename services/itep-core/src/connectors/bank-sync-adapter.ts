import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { normalizeBankTransaction, type BankTransactionEvent } from "./business-event-normalizers.js";
import type { ConnectorSyncAdapter } from "./ports.js";
export interface BankGateway {
  listTransactionChanges(input: {
    accessToken:string; externalAccountId:string; cursor?:string;
  }): Promise<{transactions:BankTransactionEvent[]; nextCursor?:string}>;
}
export class BankSyncAdapter implements ConnectorSyncAdapter {
  constructor(private readonly gateway:BankGateway,
    private readonly ingestion:SourceIngestionService,
    private readonly now:()=>Date){}
  async sync(input:Parameters<ConnectorSyncAdapter["sync"]>[0]){
    const batch=await this.gateway.listTransactionChanges({
      accessToken:input.accessToken,externalAccountId:input.account.externalAccountId,
      ...(input.checkpoint?.cursor?{cursor:input.checkpoint.cursor}:{})});
    let ingested=0,ignored=0,failed=0;
    for(const item of batch.transactions){try{
      const result=await this.ingestion.ingest(
        normalizeBankTransaction(
          input.account.organizationId,
          item,
          this.now(),
          {
            connectorAccountId: input.account.id,
            ...(input.account.legalEntityId
              ? { legalEntityId: input.account.legalEntityId }
              : {}),
          },
        ));
      result.status==="TASK_CREATED"?ingested++:ignored++;
    }catch{failed++;}}
    return {received:batch.transactions.length,ingested,ignored,failed,
      nextCheckpoint:batch.nextCursor?{cursor:batch.nextCursor}:{}};
  }
}
