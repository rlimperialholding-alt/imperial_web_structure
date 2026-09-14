# MKT-001 — Élő kódtérkép

Forrásállapot: `agent/houseplan-ui-v1` / telepített `faac4cf8d0c51294e17337f60f8f9dc9905098b9` (2026-08-11)
Adatbázis-head: `20260811_0060`

## Meglévő kapcsolódási pontok

| Terület | Élő elem | MCI kapcsolat |
|---|---|---|
| Modulregiszter | `ModuleRegistry`, `seed.py`, 47 elemű `platform_demo_seed.json` | új `market-creative-intelligence` modul, célállapot 49 a Háztervezővel |
| Marketing | `/marketing`, `marketing-control` | MCI dashboard link és read-only research handoff |
| Brief | `CopyBriefRecord`, `create_copy_brief` | csak érvényes ResearchPack hivatkozás/hash alapján brief input |
| Forrás | `CopySourceRecord`, `register_copy_source` | nem helyettesíti MCI SourceSnapshotot; kontrollált projection/handoff |
| Tartalom | `ContentAssetRecord` és többlépcsős QA | MCI nem írhat content state-et és nem publikálhat |
| Publikáció | website content + publication delivery | nincs MCI hívás; szerződés szerint tiltott |
| Audit/outbox | közös audit és `OutboxMessage` | pack handoff és invalidation események |
| AI | meglévő AGT-017 | nincs új agent identity |
| Jogosultság | `MarketPermissionGrant`, signed replica API | monoton ITEP replica, explicit allow/deny, brand/market scope, deny-first, author != approver |

## Még nyitott komponensek

- a public-fetch worker elkészült és alapból OFF; a tartós, targetenkénti elosztott rate-limit elkészült, nyitott a nagy terhelésű hálózati e2e bizonyítás;
- elkészült a külön kill switch mögötti, SHA-256 token-regiszteres, lejáró, explicit permission- és brand/market-scope kötött `/api/v1/market-intelligence` service API és OpenAPI example-csomag;
- a connector/admin health, auditböngésző és belső outbox nézet elkészült; nyitott a 10k+ performance/e2e bizonyítás.

## Tervezett fájlok

- `app/services/market_intelligence.py`
- `app/market_service_auth.py`
- `app/routes/market_intelligence.py`
- `app/templates/market_intelligence*.html`
- `app/models.py`, `app/schemas.py`, `app/roles.py`, `app/seed.py`, `app/main.py`
- `alembic/versions/20260810_0051_market_intelligence.py`
- `alembic/versions/20260811_0058_market_permission_grants.py`
- `alembic/versions/20260811_0059_market_capture_metadata.py`
- `alembic/versions/20260811_0060_market_evidence_encryption.py`
- `tests/test_market_intelligence_*.py`
