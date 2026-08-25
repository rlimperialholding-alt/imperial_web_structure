# Telek Acquisition v1 – as built

## Cél

A családi házas beépítésre alkalmas teleklehetőségek közös, bizonyítható kezelése a
meglévő Imperial Intelligence Platformban. A megoldás nem hoz létre második CRM-et vagy
adatbázist: a Growth Ops, PlotCheck, House Catalog, BuildConfig és a közös durable outbox
szolgáltatásait bővíti.

## Végrehajtott folyamat

1. Egy engedélyezett forrásconnector `residential_building_plot` Growth Signalt ad át.
2. A Growth Worker idempotensen létrehozza/frissíti a `land_opportunities` rekordot.
3. Forrásverzió-változás törli a korábbi forrásjóváhagyást és új ellenőrzést követel.
4. Megkeresés kizárólag a Growth Ops meglévő jogalap-, consent-, suppression-,
   sender-domain-, release-token- és kill-switch kapuin keresztül történhet.
5. DEAL csak a közös Growth Ops ledgerben rögzített válasz és külön DEAL-bizonylat után
   állítható be.
6. A hirdetési meghatalmazás időkorlátos, scope-olt és négy-szem jóváhagyású.
7. Hirdetési csomag csak az alábbi kanonikus bizonyítékokból készül:
   - finalizált `FIT` / `FIT WITH CONDITIONS` PlotCheck;
   - aktív és kiadott House Catalog verzió;
   - jóváhagyott, aktuális BuildConfig verzió;
   - jóváhagyott pricing, margin és cashflow kapu;
   - legalább 35% margin és legalább 20% cash buffer.
8. A generált hirdetéscsomag tartalomhash-e változtathatatlan. A készítő nem hagyhatja
   jóvá a saját csomagját.
9. Publikálás csak scope-olt, engedélyezett licensed API adapterhez kerülhet az outboxba.
10. Siker kizárólag külső azonosító, megfelelő domainű publikus URL és read-back proof
    után rögzíthető.
11. Lejárt/visszavont meghatalmazás vagy inaktív forráshirdetés automatikusan
    `TAKEDOWN_REQUIRED` állapotot és idempotens visszavonási feladatot hoz létre.

## Forrás- és portálpolitika

A generic Growth route scanner nem olvassa az `ingatlan.com`, `zenga.hu`, `dh.hu`,
`oc.hu`, `jofogas.hu`, `koltozzbe.hu` és `ingatlannet.hu` oldalakat. Ezekhez kizárólag
írásban engedélyezett API/feed connector használható. A scanner ezen felül elutasítja a
nem HTTPS, credentialt tartalmazó, nem szabványos portú, private, loopback, link-local,
reserved és CGNAT célokat. Éles környezetben resolving egress proxy/allow-list is
kötelező a DNS-rebinding ablak lezárásához.

A `config/land-acquisition/portals.json` alapállapotban minden külső olvasást, publikálást
és visszavonást tilt. Ez szándékos: a repositoryban jelenleg nincs bizonyított szerződés,
API-credential, portálspecifikus adapter-receipt vagy staging contract-test.

## E-mail jogalap

- Magánszemély címzett esetén automatikus megkereséshez explicit kérés/hozzájárulás és
  annak bizonyítékazonosítója szükséges.
- Nyilvános üzleti role mailbox csak a Growth Ops meglévő `public_business_contact`
  szabályával használható.
- Bounce, complaint, unsubscribe vagy suppression esetén minden további üzenet tiltott.
- A telekmodul nem küld e-mailt közvetlenül, így nem kerülhető meg a közös policy.

## Belső API

Minden végpont `X-Internal-Job-Token` védett.

- `POST /api/internal/land-acquisition/sync`
- `POST /api/internal/land-acquisition/opportunities/{id}/verify`
- `POST /api/internal/land-acquisition/opportunities/{id}/deal`
- `POST /api/internal/land-acquisition/opportunities/{id}/authority`
- `POST /api/internal/land-acquisition/opportunities/{id}/packages`
- `POST /api/internal/land-acquisition/packages/{id}/approve`
- `POST /api/internal/land-acquisition/packages/{id}/publish`
- `POST /api/internal/land-acquisition/attempts/{id}/confirm`
- `POST /api/internal/land-acquisition/authorities/{id}/revoke`
- `POST /api/internal/land-acquisition/opportunities/{id}/listing-state`
- `POST /api/internal/land-acquisition/takedown-scan`
- `GET /api/internal/land-acquisition/readiness`

## Aktiválási kapuk

Egy portál `discovery_enabled` vagy `publish_enabled` mezője csak akkor állítható true-ra,
ha mindegyik feltétel teljesült:

1. platformtól kapott írásos API/feed és hirdetésfeladási jogosultság;
2. jóváhagyott DPIA, megkeresési jogalap és adatmegőrzési szabály;
3. managed secretben tárolt, legkisebb jogosultságú credential;
4. adapter idempotencia-, rate-limit-, publish-, read-back- és withdrawal contract-test;
5. egress allow-list és adapter domain pinning;
6. staging canary, kézi összevetés és rollback-próba;
7. Legal + Operations review a registry-változáson.

## Jelenlegi release-határ

Az adatmodell, migráció, orkestráció, biztonsági kapuk, API és worker-integráció kész. A
név szerint felsorolt portálok és az Imperial telekkereső éles connectorai nincsenek
bekapcsolva, mert azokhoz ebben a környezetben nincs bizonyított platformjogosultság,
credential vagy adapter contract. A rendszer ezért nem állít hamis publikációs sikert.
