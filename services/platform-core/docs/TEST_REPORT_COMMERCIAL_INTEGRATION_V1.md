# Commercial Integration v1.0 – tesztjelentés

## Automatizált tesztek

- Imperial Intelligence alkalmazástesztek: **80/80 sikeres**.
- Kanonikus Contract Generator v0.4 saját tesztjei: **15 részteszt sikeres**.
- Összes sikertelen teszt: 0.

## Bizonyított szabályok

1. A Drive-ról származó Contract Generator ZIP SHA-256 lenyomata egyezik a jóváhagyott hash-sel.
2. Mind az öt master sablon hash-e megfelel a kanonikus registrynek.
3. A generálás a kanonikus v0.4 motort használja.
4. A generált csomag és manifest a Workspace dokumentumtárába kerül.
5. A projektállapot rögzíti, hogy párhuzamos üzleti motor nem készült.
6. Ugyanazon szerződésszám másodszori generálása blokkolt.
7. A ChangeControl állapot csak forrásmodul-projekcióként jelenik meg.
8. Ismeretlen párhuzamos modul kiadása jóváhagyott discovery nélkül `discovery_blocked`.
9. Jóváhagyott `integrate` discovery után a kiadás eljuthat az artifact-kapuig.
10. A Commercial Integration, szerződésadapter és Reuse Gate oldalak bejelentkezés után elérhetők.

## Migráció

- Tiszta Alembic-upgrade: sikeres.
- Alembic head: `20260719_0006`.
- Adatbázistáblák: 46.
- `cc_development_discovery`: létrejött.
- `cc_releases.discovery_request_id`: létrejött.
- `cc_releases.reuse_gate_passed`: létrejött.

## Reszponzív ellenőrzés

- Commercial Integration: 1440 px és 390 px, túlnyúlás nélkül.
- Szerződésgeneráló adapter: 1440 px és 390 px, túlnyúlás nélkül.
- Development Governance: 1440 px és 390 px, túlnyúlás nélkül.
- JavaScript page error: 0.
