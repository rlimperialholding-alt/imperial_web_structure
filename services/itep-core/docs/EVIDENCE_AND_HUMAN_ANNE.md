# Bizonyítékkezelés és Human Anne incidenssor

## Google Drive bizonyíték

A bizonyíték URI formátuma:

`gdrive://file/<FILE_ID>`

A gépi ellenőrzés vizsgálja:

- létezik-e a fájl;
- nincs-e a kukában;
- hozzáfér-e a beküldő;
- megfelel-e a MIME-típus;
- egyezik-e a revision fingerprint;
- gépileg ellenőrizhető-e az elfogadási feltétel.

A fájl puszta feltöltése továbbra sem zárja le automatikusan a feladatot.
Automatikus lezárás csak akkor engedélyezett, ha:

1. a feladat `UNDER_REVIEW` állapotban van;
2. van elfogadott bizonyíték;
3. az evidence requirement `machineVerifiable = true`.

## Human Anne incidenssor

Incidens keletkezik többek között:

- sikertelen bizonyíték-ellenőrzésnél;
- jogi, pénzügyi, hatósági vagy reputációs bizonytalanságnál;
- rendszerellentmondásnál;
- tartós P1-es késésnél;
- dead-letter értesítésnél;
- emberi döntést igénylő esetben.

Állapotok:

- OPEN
- ACKNOWLEDGED
- IN_PROGRESS
- RESOLVED
- DISMISSED
