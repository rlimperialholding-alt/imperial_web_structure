# Imperial Intelligence – integrációs architektúra

## Kanonikus helyi modell

Az integrációs prototípus három adatforrást választ szét:

- `platform.json`: alap üzleti törzsadatok, 39 modul és stabil útvonal;
- `system.json`: szerepkörök, modulteszt-rekordok, event contractok,
  HouseBuild- és Campaign Factory fixture-ök;
- böngésző `localStorage`: kizárólag a felhasználó által indított helyi
  tesztfutások, outbox és eseménynapló.

Az adatmodell szintetikus. A rendszer nem hív Drive-ot, CRM-et, CMS-t,
hirdetési platformot vagy más külső API-t futásidőben.

## Funkcionális területek

| Terület | Modulok |
| --- | --- |
| Áttekintés | Workspace, Executive Dashboard, Control Center, Integration Control Room |
| Ügyfél és értékesítés | CRM, Sales, Contract Generator, Booking, Reservation, MyImperial |
| Típusház és műszaki | House Catalog, HouseBuild, HouseMatch, PlotCheck, BuildConfig, PlanCheck, Engineering Workspace, HouseVision |
| Projekt és teljesítés | Project Control, Digital Project Managers, Smart Calendar, ChangeControl, Document & Evidence, Procurement, Partner Connect/Control/Field, Finance, Imperial Care |
| Marketing és web | Marketing Control, Campaign Factory, Content Factory, Claim Registry, Website Content Control, Answer Center, Lead Intelligence |
| Irányítás | Workflow Center, Completion Audit, Admin |

## Szerepkörök

A 12 tesztszerepkör: tulajdonos, ügyvezető, marketing, műszaki előkészítő,
értékesítő, pénzügy, projektmenedzser, tervező partner, alvállalkozó, ügyfél,
jogász és platformadmin. A választó a munkaterület navigációját szűri, de nem
helyettesít backend RBAC/ABAC ellenőrzést.

## Modulok közötti adatátadás

A `system.json` producer–consumer event contractokat tartalmaz, többek között:

- HouseBuild → PlanCheck → BuildConfig;
- HouseMatch → CRM / PlotCheck / BuildConfig;
- Contract Generator → CRM / Project / Finance / Document & Evidence;
- ChangeControl → MyImperial / Finance / Smart Calendar;
- Campaign Factory → Content Factory / Claim Registry / Marketing Control;
- Content Factory → Control Center / CRM / Marketing Control.

A kliens minden tesztművelethez correlation ID-val ellátott helyi eventet és
outbox-rekordot készít. Ez a delivery, retry és idempotencia felületét demonstrálja;
valódi üzenetközvetítő nincs mögötte.

## Production előtt kötelező

- központi identitáskezelés és backend authorizáció;
- kanonikus API-sémák, tartós event broker, idempotens consumer és DLQ;
- titkosított adattár, auditmegőrzés és adatvédelmi szabályok;
- jóváhagyott Drive/DMS, CRM, naptár, CMS és hirdetési adapterek;
- teljes adat-migrációs, terhelési, biztonsági és accessibility UAT;
- emberi jóváhagyási kapuk szerveroldali kikényszerítése.
