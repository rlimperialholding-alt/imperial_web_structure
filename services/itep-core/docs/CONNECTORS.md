# Connector Runtime v0.8

A connector account külön tárolja a Google-fiók azonosítóját, státuszát,
engedélyeit és utolsó sikeres szinkronját. OAuth token nem kerül az adatbázisba:
azt egy külső secret provider adja át futásidőben.

A Gmail connector historyId, a Calendar connector syncToken checkpointot használ.
Sikeres feldolgozás után a checkpoint mentésre kerül. Tokenhiba esetén a kapcsolat
REAUTH_REQUIRED állapotú, és Human Anne-incidens keletkezik.

Human Anne review API:
- GET /v1/ingestion/review
- POST /v1/ingestion/review/:id/approve
- POST /v1/ingestion/review/:id/reject

Connector API:
- POST /v1/connectors/:id/sync
- POST /internal/connectors/sync-all
