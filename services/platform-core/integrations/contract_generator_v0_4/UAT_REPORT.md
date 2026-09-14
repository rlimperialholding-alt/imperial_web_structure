# Imperial Contract Generator v0.4 – UAT jegyzőkönyv

## Összefoglaló

- Automatikus teszt: 29/29 sikeres.
- Öt szerződéstípus generálása: sikeres.
- Számlabefogadási kapu: sikeres pozitív és negatív tesztekkel.
- Vizuális DOCX-ellenőrzés: 17 dokumentum, 55 oldal.

## Fő tesztcsoportok

### Szerződés-teljesség

- szerződésfejléc mezőinek kötelezősége;
- összes CRM-azonosító kötelezősége;
- céges és személyes törzsadatok mezőnkénti kötelezősége;
- projektcím, helyrajzi szám, scope, dátumok és árak;
- nettó–áfa–bruttó számtan;
- fizetési ütem 100%-os összege;
- master SHA-256 és helyőrzőmentesség;
- elavult referenciaadatok kizárása.

### Kézbesítés és munkakezdés

- eredeti, aláírt példány megléte;
- igazolható postai/futárküldés;
- nyomkövetési szám és bizonylat;
- hivatalos e-mail-címre küldött azonos dokumentum;
- MessageID, dátum és csatolmány-hash;
- mindkét fél aláírása;
- kettős kézbesítés nélkül munkakezdési tiltás.

### Számlabefogadás

- elfogadott, kétoldalúan/jogosultan aláírt TIG vagy tervezői teljesítésigazolás;
- számla kötelező formai és tartalmi adatai;
- tételsori és összesített számtani egyezőség;
- szerződés-, projekt- és TIG-adategyezőség;
- olvashatóság, sértetlenség, duplikáció és fájlintegritás;
- hibás számla azonnali elutasítása;
- jogszabályi hivatkozásokat tartalmazó magyar visszautasító levél;
- számlakapu vevői szerződésnél nem érhető el.

### Profilok elkülönítése

- tervezőnél nincs 5%-os kivitelezési visszatartás;
- tervezőnél nincs 1%-os szolgáltatási levonás;
- tervezőnél nincs upstream TIG vagy kockázatközösségi kapu;
- tervező saját elfogadott teljesítésigazolása kötelező;
- kivitelezőnél valamennyi TIG-, visszatartási, levonási és hibalevonási kontroll működik.

## Vizuális QA

Minden generált, felhasználói szempontból érdemi DOCX dokumentum PDF-alapú renderelésen ment át. Oldalanként ellenőriztük:

- a szöveg és táblázatok kiférését;
- az aláírási blokkokat;
- a kézbesítési és számlabefogadási záradékokat;
- a magyar ékezeteket;
- az üres vagy ismétlődő oldalakat és tanúsorokat;
- a régi sablonadatok maradványait;
- a megfelelő szerződéstípushoz tartozó mellékletkészletet.

## Minősítés

A v0.4 futtatható és fejlesztői/UAT célra átadható. Ügyvédi masterjóváhagyás és célrendszeri integráció nélkül éles, automatikus szerződéskibocsátásra nem minősített.

## Fizetési határidő UAT

- tervezői 8 nap: kötelező és pontos érték; 7 vagy 9 nap blokkol;
- kivitelezői alvállalkozói 30 nap: kötelező és pontos érték; 29 vagy 31 nap blokkol;
- ügyvédi jóváhagyási státusz nem része az aláírási kapunak.
