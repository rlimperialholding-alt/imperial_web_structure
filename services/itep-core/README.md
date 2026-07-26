# Imperial Task Enforcement Protocol (ITEP)

Önálló, keretrendszer-független TypeScript domainmag az Imperial Intelligence
feladat-végrehajtási rendszeréhez.

## v0.5.0 – jelenlegi tartalom

- kötelező feladatmezők és validáció
- P1–P4 prioritási szabályok
- kétlépcsős feladatlezárás
- engedélyezett státuszátmenetek
- bizonyíték-ellenőrzési szabályok
- P1 eszkalációs események
- append-only audit eseménymodell
- Vitest egységtesztek
- Prisma/PostgreSQL adatmodell
- alkalmazási szolgáltatásréteg
- RBAC/ABAC jogosultsági kapu
- notification outbox és idempotens enforcement batch
- Prisma repository és optimistic locking
- Fastify REST API és Zod validáció
- Docker/PostgreSQL lokális futtatás
- központi e-mail-sablonmotor
- automatikus lezárás csak gépileg igazolt feltételeknél
- Human Anne incidenssor és REST API
- automatikus, gépi bizonyíték-ellenőrzés
- Google Drive bizonyítékadapter és revision fingerprint ellenőrzés
- Gmail adapter interfész
- outbox dispatcher exponential retry és dead-letter kezeléssel
- scheduler enforcement worker

## Futtatás

```bash
npm install
npm test
npm run typecheck
```

## Következő modulok

1. Prisma repository implementáció és tranzakciókezelés
2. REST API
3. scheduler worker és Gmail adapter
4. Google Drive evidence adapter
5. Calendar/Asana adapterek
6. Human Anne incident queue

- napi, heti és havi vezetői briefing
- KPI és SLA motor
- executive dashboard API
- Human Anne teendőlista

- Gmail- és Calendar-esemény normalizálás
- szabályalapú feladatfelismerés
- forrás- és szemantikai deduplikáció
- bizonytalan esetek Human Anne review queue-ja
- automatikus ITEP-feladatlétrehozás forráseseményből
- Gmail historyId és Calendar syncToken checkpointok
- connector account állapotgép és újrahitelesítési incidens
- secret-provider alapú OAuth tokenkezelés
- Human Anne ingestion review jóváhagyás és elutasítás
- OAuth state és callback életciklus
- credential vault interfész
- HMAC-aláírt webhook ébresztés
- automatikus connector sync worker
- connector health és elavult szinkron felismerés
- production konfigurációvalidáció
- aláírt identity gateway
- API idempotencia
- rate limiting
- liveness és readiness endpoint
- OpenAPI/Swagger dokumentáció
- audit hash-chain integritás
- Kubernetes deployment manifestok
- migration és seed folyamat
- backup/restore automatizálás
- smoke test
- readiness aggregátor
- production deployment runbook
- Integration Control Room backend
- connector health dashboard
- exponenciális retry és dead-letter queue
- OAuth reauth incidenskezelés
- Human Anne integrációs incidensek
- API- és worker-bootstrapba bekötött Integration Control Room
- Gmail, Google Calendar és Google Drive API gateway
- Prisma production migration
- connector sync és retry worker együttes futtatása
- identity, rate limit, OpenAPI és readiness tényleges aktiválása
- ingestion bootstrap sorrendi hiba javítása
- Billingo számla- és fizetésiadapter
- PSD2 banki tranzakcióadapter
- CRM lead- és aktivitásadapter
- közös business connector factory