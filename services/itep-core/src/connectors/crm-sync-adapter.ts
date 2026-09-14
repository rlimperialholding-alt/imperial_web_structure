import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import { normalizeCrmActivity, type CrmActivityEvent } from "./business-event-normalizers.js";
import type { ConnectorSyncAdapter } from "./ports.js";
export interface CrmGateway {
  listActivityChanges(input:{accessToken:string;externalAccountId:string;cursor?:string}):
    Promise<{activities:CrmActivityEvent[];nextCursor?:string}>;
}
export class CrmSyncAdapter implements ConnectorSyncAdapter {
  constructor(private readonly gateway:CrmGateway,
    private readonly ingestion:SourceIngestionService,
    private readonly now:()=>Date){}
  async sync(input:Parameters<ConnectorSyncAdapter["sync"]>[0]){
    const batch=await this.gateway.listActivityChanges({
      accessToken:input.accessToken,externalAccountId:input.account.externalAccountId,
      ...(input.checkpoint?.cursor?{cursor:input.checkpoint.cursor}:{})});
    let ingested=0,ignored=0,failed=0;
    for(const item of batch.activities){try{
      const result=await this.ingestion.ingest(
        normalizeCrmActivity(input.account.organizationId,item,this.now()));
      result.status==="TASK_CREATED"?ingested++:ignored++;
    }catch{failed++;}}
    return {received:batch.activities.length,ingested,ignored,failed,
      nextCheckpoint:batch.nextCursor?{cursor:batch.nextCursor}:{}};
  }
}
