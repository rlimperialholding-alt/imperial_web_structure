import type { SourceIngestionService } from "../ingestion/ingestion-service.js";
import type { ConnectorSyncAdapter } from "./ports.js";
import { GmailSyncAdapter } from "./gmail-sync-adapter.js";
import { CalendarSyncAdapter } from "./calendar-sync-adapter.js";
import { DriveSyncAdapter } from "./drive-sync-adapter.js";
import { BillingoSyncAdapter } from "./billingo-sync-adapter.js";
import { BankSyncAdapter } from "./bank-sync-adapter.js";
import { CrmSyncAdapter } from "./crm-sync-adapter.js";
import { GoogleGmailHistoryGateway,GoogleCalendarChangesGateway,
  GoogleDriveChangesGateway } from "./google-api-gateways.js";
import { BillingoApiGateway,Psd2BankApiGateway,
  GenericCrmApiGateway } from "./business-api-gateways.js";
export function createConnectorAdapters(ingestion:SourceIngestionService,
  config:{
    billingoBaseUrl:string;
    bankBaseUrl:string;
    crmBaseUrl:string;
    crmActivitiesPath?:string;
    crmAuthHeader?:string;
    crmAuthScheme?:string;
    crmWorkspaceQueryParameter?:string;
  },
  now:()=>Date=()=>new Date()):Record<string,ConnectorSyncAdapter>{
  return {
    GMAIL:new GmailSyncAdapter(new GoogleGmailHistoryGateway(),ingestion,now),
    CALENDAR:new CalendarSyncAdapter(new GoogleCalendarChangesGateway(),ingestion,now),
    DRIVE:new DriveSyncAdapter(new GoogleDriveChangesGateway(),ingestion,now),
    BILLINGO:new BillingoSyncAdapter(new BillingoApiGateway(config.billingoBaseUrl),ingestion,now),
    BANK:new BankSyncAdapter(new Psd2BankApiGateway(config.bankBaseUrl),ingestion,now),
    CRM:new CrmSyncAdapter(new GenericCrmApiGateway(config.crmBaseUrl, fetch, {
        ...(config.crmActivitiesPath
          ? { activitiesPath: config.crmActivitiesPath }
          : {}),
        ...(config.crmAuthHeader
          ? { authHeader: config.crmAuthHeader }
          : {}),
        ...(config.crmAuthScheme !== undefined
          ? { authScheme: config.crmAuthScheme }
          : {}),
        ...(config.crmWorkspaceQueryParameter
          ? {
              workspaceQueryParameter:
                config.crmWorkspaceQueryParameter,
            }
          : {}),
      }),ingestion,now),
  };
}
