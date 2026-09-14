# Imperial Contract Generator v0.4

Futtatható fejlesztői/UAT szerződéscsomag-generátor az Imperial Intelligence meglévő CRM-azonosítóira és öt kijelölt szerződésmasterre építve.

A v0.4 célja, hogy hiányos szerződés ne kerülhessen aláírásra, aláírt szerződés igazolható kettős kézbesítés nélkül ne engedélyezzen munkakezdést, és hibás vagy TIG nélküli partneri számla ne kerülhessen könyvelésre vagy kifizetésre.

## Kezelt szerződéstípusok

1. vevői kivitelezési szerződés;
2. vevői tervezési szerződés kiviteli tervekkel;
3. vevői típusterves tervezési és kivitelezési szerződés;
4. tervezői alvállalkozói szerződés;
5. kivitelezői alvállalkozói szerződés.

A tervezői és kivitelezői alvállalkozói profil külön szabályrendszert használ. Kivitelezési visszatartás, szolgáltatási levonás, upstream TIG és műszaki hibalevonási tábla nem alkalmazható tervezőre.

## Nullahibás szerződés-teljességi kapu

Aláírásra küldés előtt kötelező és ellenőrzött:

- szerződésszám, keltezés és szerződéskötés helye;
- CompanyID, PersonID, OpportunityID, ProjectID és PartnerID;
- az Imperial és a partner teljes céges vagy személyes törzsadatai;
- hivatalos cím, postázási cím, e-mail és telefon;
- cégjegyzékszám vagy nyilvántartási szám, adószám, bankszámlaszám;
- képviselő neve és tisztsége;
- magánszemélynél születési hely és idő, anyja neve és személyazonosító okmány adatai;
- projekt neve, pontos címe, helyrajzi száma és műszaki tartalma;
- kezdési és befejezési határidők, valamint szükséges közbenső mérföldkövek;
- nettó díj, áfa kulcs, áfa összege, bruttó díj és pénznem;
- 100%-ra összeadó fizetési ütem és esedékességi szabályok;
- kötelező mellékletek, jóváhagyások és master SHA-256 egyezés.

Üres, helyőrző, hibásan számított vagy elavult referenciaadatot tartalmazó csomag aláírási státusza blokkolt.

## Kötelező kettős kézbesítés

A cégszerűen aláírt szerződést:

1. legalább egy eredeti példányban igazolható, nyomkövethető postai vagy futárküldeményként; és
2. ugyanazzal a dokumentum-hash értékkel elektronikus úton a partner hivatalos e-mail-címére

is el kell küldeni.

A rendszer a ContractID-hoz rögzíti a nyomkövetési számot, a feladási vagy kézbesítési bizonylatot, az elektronikus MessageID-t, a címzettet, a küldési időt és a csatolmány SHA-256 értékét. A két csatorna igazolásáig `WorkStartAllowed = false`.

## Számlabefogadási kapu

A számlakapu kizárólag a két alvállalkozói profilnál érhető el.

Kötelező:

- aláírt és elfogadott, jogosult személy által jóváhagyott TIG vagy tervezői teljesítésigazolás;
- a számla és a teljesítésigazolás szerződés-, projekt-, teljesítési és összegadatainak egyezése;
- számlaszám, kelte, teljesítési időpont, beérkezési nap, esedékesség és fizetési mód;
- szállító és vevő neve, címe, adószáma, valamint a szállító bankszámlaszáma;
- hiánytalan tételsorok: megnevezés, mennyiség, mértékegység, egységár, nettó, áfa és bruttó összeg;
- helyes nettó–áfa–bruttó számítás és tételsori összesítés;
- olvasható, sértetlen, nem duplikált számlafájl és ellenőrzött SHA-256;
- szerződés szerinti fizetési határidő.

Bármely eltérésnél a státusz azonnal `REJECTED_IMMEDIATELY`. A rendszer magyar nyelvű visszautasító értesítést készít, a konkrét hibákkal, a javítás módjával és az Áfa tv. 168/A., 169. és 170. §-ára történő hivatkozással. A fizetési határidő csak a hibátlan, hiánytalan és befogadott számla nyilvántartási befogadási napján kezdődik.

### Kivitelezői alvállalkozó további kontrolljai

- meghiúsulási kötbér;
- jólteljesítési garancia;
- minimum 5% garanciális visszatartás minden számlából;
- minimum 1% megrendelői szolgáltatási levonás;
- előre meghatározott műszaki hibalevonási százalékok vagy összegek;
- belső TIG és upstream megrendelői TIG;
- kockázatközösségi feltételek;
- tervezőknél pontosan 8 napos, kivitelezői alvállalkozóknál pontosan 30 napos fizetési határidő;
- alvállalkozói ÁSZF-hivatkozás és explicit skontó.

### Tervezői alvállalkozó

A tervező számlája saját, aláírt és elfogadott tervezői teljesítésigazoláshoz kötött, de nem terheli kivitelezési visszatartás, 1%-os szolgáltatási levonás, jólteljesítési garancia, upstream TIG vagy kivitelezési hibalevonási tábla.

## Gyors indítás

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m imperial_contract_generator validate \
  --input examples/subcontractor_execution_valid.json

python -m imperial_contract_generator generate \
  --input examples/subcontractor_execution_valid.json \
  --registry config/templates.json \
  --templates master_templates \
  --output sample_output/subcontractor_execution

python -m imperial_contract_generator invoice-gate \
  --input examples/subcontractor_execution_valid.json \
  --invoice examples/invoice_execution_invalid.json \
  --rejection-docx sample_output/invoice_rejection_execution.docx
```

## Tesztelés

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q imperial_contract_generator tests
```

Kiadási eredmény: **29/29 automatizált teszt sikeres**. A vizuális UAT során 17 DOCX dokumentum 55 oldalát rendereltük és oldalanként ellenőriztük.

## Élesítés előtt kötelező

- az alvállalkozói ÁSZF végleges URL-jének és verziójának rögzítése;
- a műszaki levonási tábla vállalati műszaki jóváhagyása;
- CRM-, Drive-, e-mail-, postai nyomkövetési és elektronikus aláírási adapter bekötése;
- szerepkör-, jogosultság-, auditnapló- és adatvédelmi kontrollok célkörnyezeti beállítása.

## Tulajdonosi fizetési szabály

A kötelező döntésazonosító `ICG-PAY-2026-07-18`: tervezői alvállalkozóknál 8 naptári nap, kivitelezői alvállalkozóknál 30 naptári nap. Ügyvédi jóváhagyási kapu nincs.
