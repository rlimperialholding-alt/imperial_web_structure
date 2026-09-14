# Digital Anne Source Ingestion v0.7

## Támogatott források

- Gmail
- Google Calendar
- később Drive, weboldalak és külső webhookok

## Feldolgozási lánc

1. nyers esemény normalizálása;
2. forrás-fingerprint;
3. esemény deduplikálása;
4. szabályalapú kötelezettség-felismerés;
5. prioritás és érzékenység meghatározása;
6. bizonytalan eset Human Anne review queue-ba;
7. feladatdeduplikáció;
8. ITEP-feladat létrehozása;
9. forrásesemény státuszának naplózása.

Automatikus feladat csak kellően magas biztonsággal hozható létre.
Bizonytalan vagy hiányos felelős esetben Human Anne felülvizsgálat szükséges.
