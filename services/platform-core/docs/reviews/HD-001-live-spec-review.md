# HD-001 — Specifikációs review, 1. kör

Review tárgy: `specs/HD-001-house-designer-v0.1.md`  
Review mód: a szerzői körtől időben elkülönített adversarial pass  
Első verdikt: BLOCKED  
Végső re-review: PASS

## P0

Nincs.

## P1 blokkolók

1. **Invalidation mátrix hiányos.** Nem teljesen normatív, hogy mely változás mely compliance/price/schedule/render/snapshot állapotot teszi stale-lé, és hogyan tér vissza a session az állapotgépbe.
2. **Szabályforrás lifecycle hiányos.** A `RegulatoryRuleSet` szerepel, de a nyers forrás immutable snapshotja, kézi értelmezésének review-ja, revoke/supersede hatása és a latest-approved választás tranzakciós kapuja nincs elég pontosan definiálva.
3. **Szerkesztési command contract alulspecifikált.** A műveletek fel vannak sorolva, de nincs közös envelope, determinisztikus ID/idempotency, base revision és all-or-nothing eredmény; független kliens nem implementálható biztosan.
4. **Anonim → azonosított tulajdonátadás kockázatos.** A vendég session mentése szerepel, de nincs egyszer használatos claim, lejárat, rotation és session-fixation elleni szabály.
5. **A „megrendelés” joghatása nem egyértelmű.** A submission lehet megrendelési szándék vagy kötelező ajánlat; fizetés/árgarancia nélkül nem nevezhető végleges megrendelésnek. Explicit `ORDER_REQUEST`, verziózott tájékoztató és szerződés-előkészítési határ kell.
6. **Production provider és release flag kapcsolat hiányos.** A render/ár/kapacitás szolgáltatás hibája vagy mock provider mellett egyértelműen blokkolni kell az elfogadást/beküldést; nem csak általános release-kapu szinten.
7. **Ruleset selector konkurencia.** Check közben új ruleset revision/revoke történhet; a runnak parent-scope lock + latest-approved recheck szükséges, különben visszavont szabályból PASS keletkezhet.

## P2

- Offline queue titkosítási és recovery mechanizmusa külön technikai designban részletezendő.
- A vászon 200 objektumos p95 célját böngésző/device profillal kell mérhetővé tenni.
- A telek geometriájának koordinátarendszere és pontosság-besorolása részletezendő.

## Kötelező javítás

A v1.0 fagyasztás csak a hét P1 normatív feloldása és negatív AC-k hozzáadása után engedélyezett.

## Végső re-review

Mind a hét P1 feloldva: explicit invalidation mátrix; source snapshot/interpretation/latest-lock; command envelope/idempotency; guest claim rotation; ORDER_REQUEST joghatár; provider fail-closed; concurrent ruleset recheck. AC-HD-018–023 lefedi a negatív eseteket. P0/P1 nem maradt; a v1.0 fagyasztható.
