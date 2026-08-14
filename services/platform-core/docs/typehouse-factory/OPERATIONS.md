# Üzemeltetés

## Normál működés

1. Jogi szerepkör létrehozza, a tulajdonos/jogi jóváhagyó aktiválja a rights grantet.
2. A felhasználó egy URL-t vagy legfeljebb 1000 URL-es UTF-8 TXT/CSV/JSON listát ad.
3. A `typehouse-worker` globálisan egy jobot claimel lease- és fencing-token mellett.
4. A felület és a státusz API mutatja a terminális okot; a package végpont a QA előtt zárt.

## Incidens

Az érintett streamet azonnal szüneteltetni kell. A worker újraindítható: a lejárt lease ismét claimelhető, a fencing-token kizárja a régi worker írását. Jog- vagy forrásazonossági hiba esetén nem retry, hanem bizonyítékjavítás és új revision szükséges.

## Rollback

Állítsd le a `typehouse-worker` szolgáltatást, állítsd vissza az előtelepítési alkalmazásmentést, majd csak igazolt DB-visszaállítási döntés után futtasd a migráció downgrade-ját. A Factory-táblák eldobása adatvesztő; elsődlegesen a worker kikapcsolása és az alkalmazásverzió visszaállítása javasolt.
