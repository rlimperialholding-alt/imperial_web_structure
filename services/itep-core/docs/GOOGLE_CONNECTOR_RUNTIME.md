# Google connector runtime v1.3

A worker process most már tényleges Gmail-, Google Calendar- és Google Drive API gatewayeket indít.
A staging tokenforrás a `CONNECTOR_ACCESS_TOKENS_JSON` környezeti titok. Productionben ezt
Secret Manager/KMS alapú vault implementációra kell cserélni; token nem kerülhet adatbázisba vagy logba.

## Kötelező scope-ok
- Gmail: `gmail.readonly`
- Calendar: `calendar.readonly`
- Drive: `drive.metadata.readonly`

## Futási lánc
ConnectorSyncWorker → ConnectorSyncOrchestrator → Google gateway → SourceIngestionService → ITEP.
Hiba esetén az orchestrator Human Anne incidenst és Control Room snapshotot készít; a retry worker
exponenciális újrapróbálást, majd dead-letter áthelyezést végez.
