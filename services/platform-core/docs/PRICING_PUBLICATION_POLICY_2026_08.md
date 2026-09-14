# 2026. augusztusi marketingár-publikációs szabály

Hatályos: 2026-08-01–2026-08-31. Jóváhagyás rögzítve: 2026-07-31.

## Automatikusan elfogadható árforrás

1. A központi, hash-ellenőrzött árforrásból és verziózott kalkulációs szabályból
   determinisztikusan előállított ár külön árelfogadás nélkül publikálható.
2. Ha az adott márkához nincs aktív kalkulációs út, a hivatalos márkaweboldal aktuális,
   snapshotolt és hash-ellenőrzött ára használható külön árelfogadás nélkül.
3. Más forrásból származó, következtetett vagy kézzel kitalált ár nem használható.

## Kötelező megjelenítés

- minden ügyféloldali ár nettó HUF;
- minden ár mellett kötelező a `+ ÁFA` jelölés;
- bruttó ár marketinganyagban és ügyféloldali kalkulátornézetben nem jelenhet meg;
- a kalkulátor bruttó mezői csak belső kompatibilitási/számítási adatok, a publikációs kapu
  nem fogadhatja el őket.

## Auditnyom

Minden automatikusan továbbengedett árhoz rögzíteni kell a márkát, a modellt vagy ajánlatot,
a forrást és annak hashét, a forrás ellenőrzési idejét, a kalkuláció bemeneteit, a szabályverziót,
a nettó eredményt, a megjelenített összeget és a kapudöntést.

## Ami továbbra is blokkol

- ellentmondó, elavult vagy nem ellenőrizhető forrás;
- hiányzó modell- vagy ajánlatazonosító;
- nem igazolt akció, ajándék vagy jogosultsági feltétel;
- tiltott fedezet vagy kockázati küszöb megsértése;
- hiányzó kötelező kép, jogi tájékoztatás vagy adatkezelési feltétel;
- bármely R6–R7 külső kötelezettségvállalás vagy publikálás, amelyhez emberi jóváhagyás kell.

Ez a szabály az ismételt árelfogadási blokkot szünteti meg. Nem engedélyez automatikus
szerződésmódosítást, felelősségelismerést, teljesítésigazolást vagy más jogi kötelezettségvállalást.
