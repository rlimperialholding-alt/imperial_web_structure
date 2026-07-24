# Commercial Integration v1.0 – As-Built

## Rendszerszerep

A modul a már elkészült Contract Generator és ChangeControl közös Workspace-megjelenítési és esemény-orchestration rétege. Nem másolja le és nem írja felül egyik forrásmodul üzleti tranzakcióját sem.

## Kötelező no-duplicate kapu

A kanonikus szabály a Drive-ban meglévő **IIP System Administration and Access Management Specification v1** dokumentumba és a Control Center **Kiadási kapuk** táblájának első kapujába került.

Kiadás csak akkor haladhat tovább, ha a discovery rekord tartalmazza:

- a keresett kifejezéseket;
- a talált Drive- és release-artifactokat;
- a kanonikus ModuleKey-t és objektumgazdát;
- a forrásverziót és – ahol elérhető – SHA-256 lenyomatot;
- a reuse/extend/integrate/repair vagy tulajdonosi kivételdöntést;
- a ténylegesen megvalósítandó hiányt.

## Contract Generator-integráció

A rendszer a Drive-ról letöltött, SHA-256-tal ellenőrzött `Imperial_Contract_Generator_v0.4.zip` forrást használja. Az eredeti `imperial_contract_generator.core` generáló és validáló függvényeket hívja; új szerződésmotor nem készült.

Minden generálás előtt ellenőrzés történik:

- kanonikus ZIP hash;
- `templates.json` olvashatósága;
- mind az öt master sablon hash-e;
- a kanonikus validációs kapuk eredménye.

Az elkészült ZIP és manifest a Workspace dokumentumtárába kerül, majd `CONTRACT_PACKAGE_GENERATED` projektesemény és forrásmodul-projekció keletkezik.

Ugyanazon ProjectID és szerződésszám másodszori csendes generálása blokkolt. Új változatot a Contract Generator forrásmodulban kell létrehozni.

## ChangeControl-integráció

A Workspace kizárólag ChangeControl-eseményt fogad és projektállapot-projekciót készít. A payload minden esetben rögzíti:

- `source_module_is_authoritative = true`;
- `workspace_is_projection_only = true`.

Nem készült új:

- tételes árazási motor;
- fedezeti vagy cashflow-kapu;
- scope-jóváhagyás;
- ügyféldöntési motor;
- munkakezdési engedély;
- teljesítéslezárási üzleti logika.

## Webes felületek

- `/commercial` – szerződés- és ChangeControl-projekciók, forrásegészség és partnerintake;
- `/commercial/contracts/new` – kanonikus v0.4 adapter;
- `/development-governance` – discovery rekordok és reuse napló.

## Adatbázis

Új tábla: `cc_development_discovery`.

A `cc_releases` új mezői:

- `discovery_request_id`;
- `reuse_gate_passed`.

A migráció additív, a forrásmodulok tábláit nem másolja le.
