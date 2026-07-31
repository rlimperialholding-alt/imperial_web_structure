# Imperial Conversion Campaign Gate v1

## Mi változott

A kampánykoncepció, a márkák közötti elkülönítés és a végleges szerkeszthető
kreatívcsomag önálló publikációs invariáns. A korábbi pontszámok vagy adatbázis-
flagek önmagukban nem elegendők.

Az assembly után a rendszer csak akkor enged release review-t, ha az aktuális
assethez egyetlen, hitelesített `CAMPAIGN_PACKAGE_QA` rekord tartozik. A rekord
az alábbiakhoz kötött:

- CopyBrief és brand/campaign azonosító;
- aktuális copy SHA-256;
- jóváhagyott vizuális forrás SHA-256;
- szerkeszthető SVG/HTML master;
- subject mask és 1080-as render;
- minden platformexport SHA-256;
- forrásdokumentumok SHA-256 értéke;
- stratégia, copy, vizuális mérési jegyzőkönyv és márkaközi registry;
- hét, egymástól és a szerzőtől különálló reviewer.

## Kötelező reviewer-szerepek

1. marketing strategist;
2. direct-response copywriter;
3. magyar nyelvi szerkesztő;
4. brand guardian;
5. creative director;
6. legal;
7. financial.

Mindegyik `PASS` döntése ugyanahhoz az artifact-set hashhez tartozik. A platform
összeveti az identitásokat a korábban eltárolt kapudöntésekkel; kitalált reviewer
vagy eltérő hash esetén fail closed.

## Márkaközi elkülönítés

Azonos időszak más márkáinál tilos ugyanaz a `concept_id` vagy
`layout_archetype`. A normalizált teljes copy hasonlósága legfeljebb a csomagban
rögzített, maximum 0,72-es küszöb lehet. Szín-, logó- vagy fotócsere nem oldja fel
a szerkezeti azonosságot.

## Vizuális minimum

- lakóházas kreatívon legalább 75% termék-/házkép;
- minimum 40 px szerkesztett betűméret;
- nulla subject-mask metszés és nulla overflow;
- legfeljebb 2 soros főcím és kiegészítő szöveg;
- egy soros CTA;
- pontos OCR, hivatalos brand asset és downscale olvashatóság;
- színátmenet csak dokumentált kreatívigazgatói kivétellel;
- típusházkampánynál igazolt típusházkép.

## Secret-management

Repositoryn kívüli, külön secret szükséges:

- `CONTENT_CAMPAIGN_PACKAGE_SECRET` vagy `_FILE` változata;
- `IMPERIAL_RELEASE_HMAC_KEY` vagy `_FILE` változata.

Ezek nem lehetnek azonosak a nyelvi, marketing-, copywriter- vagy vizuális
review secrettel. Kulcs, token és jelszó nem kerülhet Gitbe, logba vagy Drive-
dokumentumba.

## Publikáció

Az owner által indított publikáció `publication-gate-envelope-v2` proofot hoz
létre. A release-token a konkrét assethez, brandhez, proofhoz, package-hashhez,
artifact-sethez, bundle-hashhez, emberi reviewerhez és időponthoz kötött HMAC.
Az adapter minden kötést újraszámol; eltéréskor az üzenet nem retry-zik, hanem
biztonsági `dead_letter` lesz.

Az `R6–R7` kategóriák mindig `HUMAN_ONLY`: automatikus külső
kötelezettségvállalás, szerződésmódosítás, felelősségelismerés és
teljesítésigazolás nem engedélyezhető.
