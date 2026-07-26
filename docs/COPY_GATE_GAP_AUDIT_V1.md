# Imperial Copy Gate v1.0 – gap audit

## Döntés

Az `imperial-copy-gate-v0.1.0.zip` nem önálló szolgáltatásként került be. A
használható Pydantic- és szabálymotor-elemek a meglévő `platform-core` FastAPI,
SQLAlchemy, Alembic, audit, Task és Outbox rétegeibe integrálódtak.

## Feltárt tényleges architektúra

- A Content Factory, Campaign Factory, Claim Registry és Website Content Control
  a közös platformmodul-regiszter és szintetikus cross-module runtime része.
- A tartós backend a `services/platform-core` FastAPI alkalmazás.
- Az adatmodell közös SQLAlchemy `Base`-t, Alembic migrációkat és `cc_*`
  platformobjektumokat használ.
- A felhasználói approval session-alapú szerepkörrel, a gépi endpointok API- vagy
  belső job tokennel védettek.
- Az audit, emberi feladat és értesítési átadás már meglévő `cc_audit_logs`,
  `cc_tasks` és `cc_outbox` táblákon történik.
- A Compose runtime korábbi SQLite rövidítése helyett a platform is a repository
  PostgreSQL + Docker secret mintáját használja. SQLite csak izolált unit tesztben
  maradt.

## Implementált és korábbi állapot

| Terület | Korábbi állapot | Integráció |
| --- | --- | --- |
| CopyBrief | Nem volt tartós, kötelező séma | Strukturált validátor és `cq_copy_briefs` |
| Kanonikus forrás | Dokumentált, runtime resolver nélkül | Verzió-, prioritás-, scope-, érvényesség- és konfliktusellenőrzés |
| Offer Engine | Demoazonosítók | Aktív Offer/Price/Terms/Product/HousePlan feloldás |
| Gate 1 | Általános marketingkapu | Tíz copy excellence dimenzió, 92/100, kritikus blokkolás |
| Gate 2–4 | Dokumentált routing | Egységes GateResult és meglévő AgentID-adapterek |
| Emberi approval | Nem volt kötelező a demo publikációnál | Szerkesztő + tulajdonos, aktuális content hashhez kötve |
| Publikáció | Közvetlen demo `PUBLISHED` események | Fail-closed állapotgép + DB CHECK + PublicationProof |
| Vizuális QA | Forrásjog nem volt kikényszerítve | Rights source + minimum 92 vizuális pont + nyitott hibák blokkolása |
| Teljesítmény | Főleg CTR-szintű demo | Olvasási mélységtől marginig auditált metric schema |
| Golden Copy | Nem volt elkülönített | Csak kifejezetten jóváhagyott `cq_golden_copy_samples` |

## AgentID adapterdöntés

Az AI Agent Registry v4-ben a Dr. Eötvös és Digitális Olivér megnevezés még nem
szerepel önálló új AgentID-ként. Új, párhuzamos agent létrehozása helyett a meglévő
szerződésekhez készült adapter:

- Gate 1 Marketing Quality: `AGT-017` Marketing Intelligence Agent;
- Gate 2 jogi: `AGT-016` Legal Case Agent;
- Gate 3 pénzügyi: `AGT-011` Finance Agent;
- Gate 4 műszaki: `AGT-013` Quality and E-log Agent.

Az aliasok később registry-migrációval átnevezhetők, de a gate contract és az
auditban tárolt AgentID stabil marad.

## Megszüntetett bypassok

A szintetikus Campaign Factory, Content Factory és Website Content Control
demoakciói már nem állítanak elő `APPROVED` vagy `PUBLISHED` állapotot. Csak
Copy QA-, szerkesztői- vagy tulajdonosi review-kérést eseményeznek. Valódi
`PUBLISHED` állapot kizárólag a tartós content-quality API-n hozható létre.
