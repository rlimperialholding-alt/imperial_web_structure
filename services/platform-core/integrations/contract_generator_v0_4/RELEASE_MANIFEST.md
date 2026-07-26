# Imperial Contract Generator v0.4 – Release Manifest

**Kiadás dátuma:** 2026-07-18
**Állapot:** futtatható fejlesztői / UAT kiadás; production-ready minősítés nélkül

## Elkészült

- öt külön szerződésprofil és automatikus típuskiválasztás;
- minden kötelező szerződésmező, ár, cím, személyes és céges adat blokkoló ellenőrzése;
- nettó–áfa–bruttó számítás és 100%-os fizetési ütem ellenőrzése;
- változatlan masterfájlok SHA-256 integritásvédelme;
- mezőszintű DOCX-kitöltési audit és helyőrzőkeresés;
- elavult referencia-nevek, bankszámlák, adószámok és aláírók kiszűrése;
- igazolható postai/futár és elektronikus kettős kézbesítési kapu;
- mindkét fél aláírásához és kézbesítési bizonyítékhoz kötött munkakezdési engedély;
- tervezői és kivitelezői alvállalkozói számlakapu;
- aláírt és elfogadott TIG/teljesítésigazolás, tételes formai és tartalmi számlaellenőrzés;
- hibás számla azonnali `REJECTED_IMMEDIATELY` státusza és jogi szövegű visszautasító levél;
- a vevői szerződéscsomagokból az alvállalkozói számlakapu eltávolítása;
- külön kivitelezői műszaki megfelelőségi és levonási melléklet;
- tervezőknél a kivitelezési visszatartási és upstream kontrollok kizárása.

## UAT

- automatizált tesztek: **29/29 sikeres**;
- Python szintaktikai/fordítási ellenőrzés: sikeres;
- renderelt dokumentumok: **17 DOCX**;
- vizuálisan ellenőrzött oldalak: **55 oldal**;
- ellenőrzött területek: tördelés, táblázatok, aláírási blokkok, ékezetek, helyőrzők, ismétlődő tanúsorok, régi törzsadatok, típusonkénti mellékletlogika.

## Kiadott mintacsomagok

- `sample_output/customer_construction.zip`
- `sample_output/customer_design_execution_plans.zip`
- `sample_output/customer_type_house_design_build.zip`
- `sample_output/subcontractor_design.zip`
- `sample_output/subcontractor_execution.zip`
- `sample_output/invoice_rejection_execution.docx`

## Tulajdonosi döntés alapján lezárt fizetési szabály

A tervezői alvállalkozói szerződés fizetési határideje 8 naptári nap, a kivitelezői alvállalkozói szerződésé 30 naptári nap. Az ügyvédi jóváhagyási blokkoló megszűnt; a döntésazonosító ICG-PAY-2026-07-18.
