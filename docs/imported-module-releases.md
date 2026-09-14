# Beemelt modulkiadások és forrásprovenance

Ez a jegyzék a helyi, szintetikus Imperial Intelligence tesztplatform
forrásdöntéseit rögzíti. A Google Drive a specifikációk és átadási csomagok
kanonikus forrása; a futtatható kód, teszt, migráció és Docker-konfiguráció
kanonikus helye ez a repository.

## Közös platformmag

A `services/platform-core` a Commercial Integration v1.0 kiadás ellenőrzött
forrásfájljaira épül. Megőrzi a közös ProjectRegistry, esemény/outbox, audit,
Workspace, Project 360, Import Center, TenderMail, kalkulátor, HouseMatch,
BuildConfig, Operations, Partner Field, Procurement és Contract Generator
adaptereket. Erre épül az összes portálmodul közös, JSON-alapú demo runtime-ja.

| Kiadás | Drive fájlazonosító | Beemelési mód |
| --- | --- | --- |
| Commercial Integration v1.0 | `19Pik8vTzP86RAVwDG_VxtJl99HjwWiLx` | közös platformmag |
| Contract Generator v0.7 | `1uYdu4lMfqZ-hEvO00BGwuu2KF_HH42uv` | forrásellenőrzés; a platformadapter kompatibilis v0.4 motorral fut |
| Smart Calendar v1.1 | `1O21BircicmcmOONUWtjHDqFD5Q552gz4` | közös esemény- és UI-adapter |
| Procurement v1.0 | `1YlZYCA5Y2GX-91PbdxRPjEZJGtu2LWtI` | platformmag + demo adapter |
| Operations + Partner Field v1.0 | `1O3EvnjMD_JICiHnIymZtmwQexwtRLNhb` | platformmag + Operations/Field nézetek |
| CRM pilot v1.3 | `1OjDYOLB_y-vWVHySyBc-vx_wLgAj1gSm` | közös CRM-adat- és eseményszerződés |
| CRM + MyImperial v1.0 | `1tsmX6LrqZWzwOw7yAc8nN9uHboVq6yM9` | CRM/MyImperial felületi és útvonaladapter |
| CRM Configurator v1.2 | `1yN57y2Nf0myeHVZPY8hkbs5urVezkMss` | BuildConfig/Sales adapter |
| Marketing Automation v1.3 | `1521Rv3ag5Z_WbVPd6zgI4STGnO1zr-5t` | Campaign/Content/Claim/attribúciós demo |
| Finance v1.0 | `1orIcbbYbRjr9kAVU-hERL3yM-RpN5vIYf` | Finance Intelligence és könyvelői nézet |
| Control Center v1.0 | `1AKNi31abFtx368bHrqdiOuGy64TlJy8P` | Control Center, Completion Audit, ICR |
| Document & Evidence v1.1 | `15MhSC5-kkvG8AY2xEi5wlamwIdPurfer` | Document Center/Evidence/Intake adapter |
| Executive Dashboard v1.1 | `1Q690xh2j2BqNa_Bow_RYcdvjaydiK3i5` | ügyvezetői Workspace adapter |
| Engineering Workspace handoff v1.0 | `1Wx8bUt3w1fOgEZF7F1hS8XgbF-L8GiI8` | műszaki workspace és kapumodell |
| Engineering kattintható prototípus | `1LN3CH7N6Z-IyIurzQcYKE4rp-QYcRhhR` | felületi referencia |
| Migration Engine v0.2.0 | `1zB3igR3mCW2tU4FHi-birRL3vNcHg90l` | import/reconciliation referencia |

## Specifikációból integrált modulok

A következő modulok Drive-mappájában nem volt önálló futtatható ZIP, ezért a
kanonikus specifikáció és a közös platform szerződései alapján működő sandbox
adapter készült: PlanCheck, PlotCheck, ChangeControl, Partner Connect /
PartnerCheck, Imperial Care és HouseVision. Ezek nem production motorok, de
stabil azonosítóval, demo rekorddal, művelettel, eseménykézbesítéssel és E2E
tesztlefedettséggel rendelkeznek.

## Biztonsági határ

- minden személy, projekt, partner, ár és dokumentum szintetikus;
- nincs külső API-hívás, hirdetési publikálás vagy valódi e-mail-küldés;
- nincs production secret;
- a sandbox műveletek ugyanazokat az integrációs invariánsokat demonstrálják,
  amelyeket az éles adaptereknek majd ki kell kényszeríteniük: ProjectID,
  CorrelationID, idempotency key, producer–consumer szerződés, outbox, retry,
  audit és reconciliation.
