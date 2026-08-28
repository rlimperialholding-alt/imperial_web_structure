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
4. Megkeresés kizárólag a Growth Ops meglévő forrás-, suppression-, sender-domain-,
   release-token- és kill-switch kapuin keresztül történhet. A hirdetésben megadott
   címzettet `listing_agent` vagy `property_owner` szerepkörbe kell sorolni; ismeretlen
   szerepkörrel nem készül telekspecifikus levél.
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

A generic Growth route scanner az `ingatlan.com`, `zenga.hu`, `dh.hu`, `oc.hu`,
`jofogas.hu`, `koltozzbe.hu` és `ingatlannet.hu` nyilvános HTML-oldalait csak explicit
`public_html` registry-bejegyzéssel olvashatja. Minden kérés előtt érvényesíti a portál
`robots.txt` szabályát, azonosított Imperial user agentet használ, és nem kerül meg
bejelentkezést, CAPTCHA-t, paywallt, 403/429 választ vagy más technikai korlátozást. A
scanner ezen felül elutasítja a nem HTTPS, credentialt tartalmazó, nem szabványos portú,
private, loopback, link-local, reserved és CGNAT célokat. Éles környezetben resolving
egress proxy/allow-list is kötelező a DNS-rebinding ablak lezárásához.

A `config/land-acquisition/portals.json` alapállapotban engedélyezi a robots-aware
nyilvános HTML-beolvasást, de a readiness csak akkor PASS, ha a Hetzner forráskatalógusban
van legalább egy aktív, az adott portálhoz tartozó route. A publikálás és visszavonás
továbbra is tiltott, mert azokhoz nincs portálspecifikus adapter-receipt vagy staging
contract-test.

Az `SRC-0012` forrássor régi `/lista/elado+telek` címe auditcélból változatlanul megmarad
a snapshotban, de futáskor a robots-engedélyezett `https://ingatlan.com/elado+telek`
útvonalra cserélődik. A listaoldal konkrét, portálon belüli hirdetéslinkjei önálló
forrásbizonyítékként kerülnek a deduplikációba; a kategóriaoldal URL-je nem helyettesítheti
a konkrét hirdetés hivatkozását.

## E-mail forrás- és címzetti kapu

- Nyilvános építésitelek-hirdetés alapján egyszeri automatikus első kapcsolatfelvétel
  engedélyezett a hirdetésben azonosított `listing_agent` vagy `property_owner` részére,
  szervezeti role mailboxon és név szerinti e-mail-címen egyaránt. Ehhez az útvonalhoz
  nem szükséges külön `explicit_request` vagy `documented_consent`; a kapcsolatfelvétel
  kizárólag a konkrét, nyilvános telekhirdetésre adott együttműködési jelentkezés lehet.
- A forráshirdetés HTTPS URL-je, a címzett szerepköre és a hirdetésből származó
  kapcsolat visszakereshető rögzítése kötelező. Más célú természetes személyes
  megkeresésre ez a kivétel nem használható.
- A változtathatatlan, tulajdonos által jóváhagyott sablon első levele a
  `land-public-listing-v3` policy alapján automatikusan release-tokenes jóváhagyást kap.
  Ez kizárólag az első levélre érvényes; automatikus utánkövető levél nem készül.
- `listing_agent` esetén a 2026-08-25-én jóváhagyott rövid levél 2,5%-os jutalékot,
  telekre illő típusházzal elkészített hirdetést, látványtervet, alaprajzot és műszaki
  leírást ajánl. A fő jutalékmondat multipart HTML levélben félkövér, a plain-text
  változatban változatlan szöveggel szerepel.
- `property_owner` esetén a 2026-08-28-án jóváhagyott levél ingyenes, jutalékmentes és
  kötelezettség nélküli telek + típusház hirdetést ajánl. A levél tárgya és törzse a
  konkrét települést, telekméretet és forráshirdetés-linket tartalmazza; hiányzó változó
  esetén a rendszer fail-closed módon nem állítja sorba.
- Nyilvános üzleti role mailbox továbbra is a Growth Ops meglévő
  `public_business_contact` szabályával használható.
- Bounce, complaint, unsubscribe vagy suppression esetén minden további üzenet tiltott.
- Ingatlanos címzettnél külön, pontszámmal és kézi release-zel sem felülírható hard gate
  tiltja Turczer Józsefet, a teljes GDN Ingatlanhálózatot, valamint az Otthon Centrum
  II./II/A. és XII. kerületi irodáinak minden munkatársát. Az ismert OC-irodaazonosítók
  közé tartozik a Bem rakpart, TDG, Hidegkúti út, Lajos utca, Ürömi utca, MOM Park és
  Városmajor utca. OC-s címzett ellenőrzött iroda-hozzárendelés nélkül, illetve bármely
  ingatlanos ellenőrzött hálózati/irodai affiliáció nélkül fail-closed módon blokkolt.
- A kizárás a forrásrekord befogadása, az üzenet sorba állítása, a release és a tényleges
  SMTP-kiküldés előtt is lefut; a már korábban sorba állított tiltott címzett státusza
  `blocked` lesz, auditált tiltási indokkal.
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

Egy portál `public_html` discovery módja csak akkor állítható true-ra, ha robots.txt
érvényesítés, azonosított user agent, HTTPS source route, deduplikáció és technikai
védelem-megkerülési tiltás aktív. Egy portál `publish_enabled` mezője csak akkor állítható
true-ra, ha mindegyik feltétel teljesült:

1. platformtól kapott írásos API/feed és hirdetésfeladási jogosultság;
2. jóváhagyott DPIA, megkeresési jogalap és adatmegőrzési szabály;
3. managed secretben tárolt, legkisebb jogosultságú credential;
4. adapter idempotencia-, rate-limit-, publish-, read-back- és withdrawal contract-test;
5. egress allow-list és adapter domain pinning;
6. staging canary, kézi összevetés és rollback-próba;
7. Legal + Operations review a registry-változáson.

## Jelenlegi release-határ

Az adatmodell, migráció, orkestráció, biztonsági kapuk, API és worker-integráció kész. A
név szerint felsorolt portálok nyilvános HTML-je feldolgozható, amennyiben a konkrét route
robots-engedélyezett és nem ütközik technikai védelembe. Az Imperial telekkereső éles
publikációs adaptere nincs bekapcsolva, ezért a rendszer nem állít hamis publikációs sikert.

A napi 05:30 Europe/Budapest futáshoz a Hetzner release-környezetben az alábbi nem titkos
kapcsolók szükségesek: `GROWTH_OPS_ENABLED=true`, `CANONICAL_GROWTH_ENABLED=true`,
`CANONICAL_ROUTE_SCANNING_ENABLED=true` és `CANONICAL_PROCESSING_ENABLED=true`. A levélküldés
ettől külön kapu: ellenőrzött sending domain, SMTP-secret, `ALLOW_APPROVED_WRITES` kill-switch,
30 napos címzetti cooldown, suppression-ellenőrzés és a fenti címzetti jogalap nélkül nem indul.
