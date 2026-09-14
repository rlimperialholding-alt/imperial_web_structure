# MKT-001 — Élő baseline

Dátum: 2026-08-10  
Állapot: RECORDED

- A 47 modulos élő katalógusban nincs `market-creative-intelligence`.
- Nincs `/market-intelligence` route vagy dedikált UI.
- Nincs SourceTarget/CaptureJob/SourceSnapshot/MarketAsset/Observation/VOC/Pattern/Hypothesis/ResearchPack/Validation kanonikus adatmodell.
- A meglévő marketing stack briefet, assetet, review-t és publikációt kezel; ezeket az MCI nem duplikálhatja.
- A forrás- és briefmodellekhez kontrollált handoff kialakítható.
- Production capture/publishing connector MCI-hez nincs, ezért induláskor OFF.
- A Drive master és végrehajtási utasítás elérhető és tartalmilag ellenőrzött. A source lock: file `1cL8NxgfnsZwyRqns7skTTeVG8VIMxctpX2A6fO7YnB0`, revision `7`, modified `2026-08-02T19:05:16.328Z`, reported size `79000`. A későbbi Drive másolat szövege azonos, de nem kanonikus.

Baseline quality: induló Alembic head `20260809_0049`; a HD additív csomag után `20260810_0050`. A globális legacy lint baseline FAIL és a helyi többmodulos pytest timeout dokumentált; az új fájlok külön zéró-lint kaput kapnak.

## 2026-08-10 végrehajtási bizonyíték

- `20260810_0051` additív migráció elkészült; friss SQLite `0001 → 0051` PASS, 217 tábla, ideiglenes adatbázis törölve.
- SourceTarget, CaptureJob, SourceSnapshot/redaction, asset, observation, VOC, pattern, hypothesis, validation, ResearchPack és handoff-watermark kanonikus táblák létrejöttek.
- manual/fixture vertical slice működik: target draft → review → külön reviewer approve → tisztított immutable snapshot → karakterpontos OBSERVED/INFERRED observation → hash-elt pack → review → approve → freeze.
- self-approval tiltás, idempotens/deduplikált snapshot replay, prompt-injection tiltás és manifest-hash újraellenőrzés izolált tranzakciós smoke-ban PASS.
- hitelesített marketing-felhasználós `/market-intelligence` route render PASS; új MCI Python fájlok célzott Ruff és `py_compile` PASS.
- public fetch, production blob/KMS, downstream handoff és minden kampány/publikációs side effect OFF marad; a UI ezt látható connector-health állapotként jelzi.

## 2026-08-11 release-bizonyíték

- Telepített commit: `faac4cf8d0c51294e17337f60f8f9dc9905098b9`; Alembic head: `20260811_0060`.
- A targetenkénti rate-limit a jóváhagyott immutable policy része, forráscsaládon át folytonos és target-sorzárral konkurenciabiztos; az idempotens replay nem fogyaszt új kvótát.
- Operations/audit UI és API mutatja a connector readiness, queue/running/24h failure, oldest queued, evidence encryption és belső outbox állapotot; az auditlista scope-szűrt.
- Izolált release image: Ruff PASS, format PASS, teljes MKT tesztcsomag 15/15 PASS. Telepítés után hitelesített HTML+API smoke PASS, core/worker error és traceback 0.
- A release előtt készített szerverhelyi PostgreSQL dump SHA-256 és `pg_restore --list` ellenőrzése PASS; felhőbe nem történt mentés.
