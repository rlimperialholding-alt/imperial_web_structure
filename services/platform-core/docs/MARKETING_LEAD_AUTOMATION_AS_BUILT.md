# Campaign Factory és Lead Intelligence – as-built

## Cél és határ

Az alrendszer a Marketing Control, Campaign Factory, Content Factory, Lead
Intelligence és CRM közötti üzleti láncot valósítja meg. A kampány csak
független vezetői jóváhagyással és publikált, élő QA-val ellenőrzött content
assettel aktiválható.

## Kampányfolyamat

- márka, cél, célközönség, csatornák, időszak, keret, céllead és cél-CPL;
- egyedi UTM source, medium és campaign attribúció;
- draft → review → approved → active/paused életciklus;
- négy szem elv: a létrehozó vagy benyújtó nem hagyhatja jóvá saját kampányát;
- fail-closed aktiválás: `PUBLISHED` és élő QA-val jóváhagyott Content Factory
  asset nélkül a kampány nem indítható el;
- minden létrehozás, jóváhagyás, aktiválás és szüneteltetés auditált.

## Lead Intelligence és CRM

- kampányos és organikus leadrögzítés forrás-, csatorna- és UTM-adatokkal;
- tokennel védett `POST /api/marketing/leads` adaptervégpont landingek és űrlap-backendek számára;
- kampányhoz adott, ellentmondó UTM-adatok szerveroldali visszautasítása;
- adatkezelési tájékoztató elfogadása kötelező; a marketing-hozzájárulás külön mező;
- normalizált e-mail vagy telefon alapján SHA-256 deduplikáció;
- ismételt érdeklődés új rekord helyett jelként kerül ugyanahhoz a leadhez;
- determinisztikus 0–100 pontozás keret, időtáv, helyszín, igény és elérhetőség alapján;
- 60 pont alatti MQL csak dokumentált marketingkivétellel;
- kanonikus `customer/lead` rekord és natív CRM-rekord az átadáskor;
- névre szóló értékesítői feladatkártya;
- értékesítői elfogadás vagy indokolt visszaadás a marketingnek;
- teljes lead-aktivitási idővonal és auditnapló.

A marketing-hozzájárulás nem növeli a lead pontszámát. Így az adatvédelmi döntés
nem torzítja a kereskedelmi minősítést.

## Teljesítménymérés és optimalizálás

- idempotens napi csatornametrika-import a forrásrendszer és külső kulcs alapján;
- kampányhoz és opcionálisan Content Factory assethez kötött megjelenés, kattintás,
  landing session, űrlapindítás, űrlapkitöltés, platformkonverzió és nettó költés;
- a kampány pénznemétől eltérő költés és a más kampányhoz már felhasznált külső
  kulcs fail-closed visszautasítása;
- aggregált CTR, landing leadkonverzió, MQL-arány, értékesítési elfogadási arány,
  CPL és MQL-költség;
- determinisztikus pause, scale, kreatívteszt, landingteszt vagy hold javaslat;
- a rendszer csak javasol: a költés vagy kampánystátusz kizárólag független
  owner/managing-director/platform-admin jóváhagyással módosulhat;
- kreatív- és landingtesztből névre szóló, auditált feladatkártya keletkezik;
- minden import, javaslat, döntés és végrehajtás auditált.

## Bizonyító eszközök

- `tests/test_marketing_lead_automation.py`;
- `scripts/verify_marketing_automation_schema.py`;
- `scripts/seed_marketing_automation_uat.py`.

A szerver-UAT kontrollált, szintetikus publikációs bizonyítékot, aktív kampányt,
attribútált MQL-t, idempotens költésimportot és négyszemes optimalizálási döntést
hoz létre. Az elkülönített CRM-UAT lead marketing-hozzájárulása hamis; így a
kanonikus CRM-átadás nem függ marketingcélú hozzájárulástól.
