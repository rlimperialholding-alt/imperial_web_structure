# Changelog

## 1.1.0 / Platform 4.4.0 – 2026-07-19

- Enterprise Import Center adatmodell és reszponzív adminfelület;
- pénzügyi, projekt-, partner-, ügyfél-, beszerzési, szerződéses és termékadat-osztályozás;
- staging, validáció, deduplikáció, emberi jóváhagyás, commit és rollback;
- CSV/JSON/XLSX/TXT kézi import;
- connector push API Gmail/Drive/Sheets adapterekhez;
- ProjectID és ProjectFact integráció;
- 2026-07 jóváhagyott kalkulációs források zárolása Drive ID-val és SHA-256-tal;
- újépítési és felújítási kalkulátor API és webes felület;
- HouseMatch eredeti katalógus és pontozás webes/API bekötése;
- BuildConfig vizuális konfigurációs felület;
- TenderMail kampány-, címzett-, domainhitelesítési, suppression- és kézbesítési réteg;
- éles provider nélküli biztonságos küldésszimuláció;
- Alembic 20260719_0002;
- 29/29 automatizált teszt.

## 1.0.0 – 2026-07-19

- 15 modulos modulregiszter és heartbeat;
- közös ProjectID-, esemény-, objektum- és feladatvetület;
- idempotens event gateway;
- outbox/retry/dead-letter;
- hét rendszerközi konzisztenciaszabály;
- tulajdonosi/ügyvezetői kivételcockpit;
- release, artifact, environment és deployment kapuk;
- három szintetikus E2E integrációs pilot;
- PostgreSQL/Docker production alap;
- Alembic 20260719_0001;
- 20/20 automatizált teszt.

## 1.2.0 / Platform 4.7.0 – Workspace v1.0
- Közös Imperial Intelligence app shell és oldalsó navigáció.
- Személyes Workspace kezdőlap.
- Action Center feladatkezelés és auditált állapotváltás.
- Projekt 360° közös ProjectID nézet.
- Központi dokumentumtár és `ws_documents` modell.
- Csoportosított központi kereső.
- 3 új Workspace automatizált teszt; teljes eredmény 32/32.

## 1.5.0 / Platform 5.0.0 – Commercial Integration v1.0

- kötelező „reuse first / no duplicate development” discovery gate;
- minden kiadás előtt Drive-, modul-, release- és forrásartifact-ellenőrzés;
- új kiadás `discovery_blocked`, ha nincs jóváhagyott újrafelhasználási vagy kivételi döntés;
- a Contract Generator v0.4 kanonikus, Drive-ról visszaellenőrzött forráscsomagjának változtatás nélküli adapteres bekötése;
- a Contract Generator ZIP és mind az öt master sablon SHA-256 ellenőrzése minden generálás előtt;
- szerződéscsomagok Workspace-dokumentumtári regisztrációja és Contract Generator projektállapot-projekció;
- ugyanazon szerződésszám csendes újbóli generálásának blokkolása;
- ChangeControl v0.1 esemény- és állapotprojekció új ár-, fedezet-, scope- vagy jóváhagyási motor nélkül;
- közös Commercial Integration és Development Governance webes felület;
- Alembic `20260719_0006`;
- 80/80 alkalmazásteszt és a kanonikus Contract Generator további 15 résztesztje sikeres.
