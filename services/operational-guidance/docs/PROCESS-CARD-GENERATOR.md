# Imperial Process Card Generator v0.5.0

## Szerepe

A Process Card Generator a kanonikus folyamatmodellből az öt valós munkakör egyikére kiosztott, emberi nyelvű, egyoldalas PDF- és PNG-kártyát készít. Nem önálló rendszer: az Operational Guidance Engine egyik megjelenítési és verziókezelési szolgáltatása.

## Kimeneti csomag

Minden verzióhoz együtt készül:

- Process Card PDF és PNG;
- Process Card JSON;
- kapcsolt checklist-sablon PDF és PNG;
- checklist JSON;
- közös `bundle.json`;
- jóváhagyási rekord.

A fájlútvonal szerepkör / ProcessID / verzió szerkezetet követ.

## Kötelező emberi mezők

- Mikor kell csinálni?
- Mit veszel át?
- Mit adsz át?
- Lépések – ezt csináld
- STOP – állj meg és szólj
- Kész, ha
- kapcsolt ChecklistTemplateID és GateID

## API

Minden nem-webhook végpont `X-Imperial-Token` fejlécet kér.

- `POST /api/v1/process-cards/catalog/import`
- `POST /api/v1/process-cards/ingest`
- `POST /api/v1/process-cards/{process_key}/generate`
- `POST /api/v1/process-cards/{process_key}/versions/{version}/approve`
- `POST /api/v1/process-cards/{process_key}/checklists/start`
- `POST /api/v1/process-cards/regenerate-changed`
- `POST /api/v1/process-cards/webhooks/directus` – `X-Directus-Secret` hitelesítéssel

## Integrációk

- `DirectusOperationalCatalogAdapter`: a process- és checklist-forrás közös visszaolvasása;
- `DirectusOperationalRecordSink`: kártyaverziók, sablonok és példányok közös mentése;
- `GoogleDrivePublisher`: jóváhagyott verzió publikálása;
- `GmailApprovalNotifier`: draft értesítése az ügyvezetőnek;
- Celery: 15 perces változásellenőrzés;
- n8n: üzleti esemény és kapu-orchestration.

Hitelesítő adat nincs a forráscsomagban. Google- és Directus-adapter csak kitöltött környezeti változóval aktiválódik.
