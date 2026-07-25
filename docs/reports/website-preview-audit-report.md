# Weboldalak preview — teljes forrás-, tartalom-, asset- és böngészőaudit

Dátum: 2026-07-25
Ág: `feature/platform-foundation`

## Eredmény

- Katalógus: **131 oldal / 12 márka**.
- Drive-ból visszakeresett, verziózott weboldalspecifikáció: **10 márka / 69 oldal**.
- Statikus és HTTP asset-audit: **0 hiba, 0 figyelmeztetés, 1703 sikeres helyi függőség**.
- Tartalom- és márkaaudit: **0 hiba, 0 figyelmeztetés**.
- Külső runtime kérés: **0**.
- Külső navigáció vagy forrás-metaadat: **37**; ezek nem runtime függőségek.
- Hiányzó, forrásban definiált katalógusoldal: **0**.
- Playwright-mátrix: **394/394 sikeres** (**131 × 3 nézetméret + 1
  katalógusteszt**), helyi futásidő 5,5 perc.

| Ellenőrzött hibakategória | Végleges darabszám |
|---|---:|
| HTTP 404 / nem 200 helyi függőség | 0 |
| Blokkolt külső runtime függőség | 0 |
| Nem létező helyi fájl | 0 |
| Hibás relatív vagy abszolút útvonal | 0 |
| Márkaspecifikus, közös `/assets/` hivatkozás | 0 |
| Azonos hosszú szövegblokk egy oldalon belül | 0 |
| Azonos hosszú szövegblokk külön oldalak között | 0 |
| Márkakeveredés a Prefab csomagban | 0 |
| Forrásspecifikáció nélküli automatikus helyőrző | 0 |

Az asset-crawler minden HTML `href`, `src`, `srcset`, inline `style`, CSS
`url()` és `@import`, valamint statikus és dinamikus JavaScript-import
hivatkozását rekurzívan követi. A katalógusoldalakat és minden helyi
függőséget fájlrendszeren, majd HTTP-n is ellenőrzi.

## Drive-források és arculati szabályok

A Google Drive audit során megtaláltuk a központi Conversion Architecture
v1.5 dokumentumot, a közös design-token megfeleltetést, a lokalizációs mátrixot,
valamint a márkánkénti arculati és conversion guide-okat. A korábban
„source-only” jelölésű csomagok egyetlen oldal helyett összesen 47 konkrét
oldalt írtak le. Az Imperial, Bautica és Prefab további forrásfájljai 22
fogyasztói oldalt adtak a katalógushoz.

Minden forrásalapú oldal metaadatként tartalmazza:

- a Drive-forrás azonosítóját;
- a márka arculati kézikönyvének azonosítóját;
- a `source-aligned-preview` tartalmi státuszt.

A generátor márkánként külön színeket, tipográfiát, logót, vizuális assetet,
oldaltípust és konverziós struktúrát alkalmaz. A tartalom forrásból készül, a
CTA-k pedig a következő ellenőrizhető döntésre vezetnek, nem tesznek
automatikus kötelezettségvállalást.

## Márkánkénti állapot

| Márka | Elérhető | Hiányzó | Ellenőrzött helyi hivatkozás | Forrás- és márkajavítás | Fennmaradó blokkoló probléma |
|---|---:|---:|---:|---|---|
| Imperial Holding | 27 | 0 | 196 | fogyasztói és B2B oldalak; 10 tudásoldal helyes márkához mozgatva | nincs |
| Danish Fabrik | 7 | 0 | 98 | 7 Drive-oldal, saját tokenek és vizuálok | nincs |
| Bautica | 14 | 0 | 162 | 8 fogyasztói + 6 B2B oldal, külön Bautica arculat | nincs |
| Prefab | 15 | 0 | 150 | 9 fogyasztói + 6 B2B oldal; Imperial tartalom eltávolítva | nincs |
| Casa Moderna | 7 | 0 | 98 | 7 Drive-oldal, saját tokenek és vizuálok | nincs |
| Family Homes | 13 | 0 | 223 | mind a 13 teljes HTML-oldal, oldalanként egyedi compliance-szöveg | nincs |
| Everyday Homes | 6 | 0 | 78 | 6 Drive-oldal, saját tokenek és vizuálok | nincs |
| Property 360 | 6 | 0 | 78 | 6 Drive-oldal, saját tokenek és vizuálok | nincs |
| Budapesti Magasépítő Vállalat | 15 | 0 | 318 | teljes Bootstrap/Icons és márkahelyi assetcsomag | nincs |
| BauFreund | 9 | 0 | 144 | 9 Drive-oldal, saját tokenek és vizuálok | nincs |
| RED Property | 5 | 0 | 60 | 5 Drive-oldal, saját tokenek és vizuálok | nincs |
| Timberhaus | 7 | 0 | 98 | 7 Drive-oldal, saját tokenek és vizuálok | nincs |

A korábbi, Prefab alatt tárolt többmárkás belső katalógus nem publikus
márkaoldal: `sites/_portal/review/` alá került. A Prefab csomagban nincs
Imperial Holding-, Bautica- vagy más idegen márkaszöveg.

## Assetek, navigáció és reszponzivitás

Minden márka önálló csomag: HTML, CSS, JavaScript, kép, ikon és font a saját
könyvtárában található. A Bootstrap 5.3.3 teljes minifikált CSS-e és bundle
JavaScriptje, valamint a Bootstrap Icons 1.11.3 CSS- és fontfájljai helyben
érhetők el, licencfájlokkal. Nincs CDN-, Google Fonts-, külső kép-, ikon- vagy
JavaScript-függőség.

A review bridge a márkán belüli linkeket a
`/site-preview/<brand>/...` névtérben tartja, és megőrzi a `review=1`
paramétert. A reszponzív audit javítja a Bootstrap nagy guttereinek tablet
túlcsordulását, valamint a B2B lépéssáv hosszú címkéinek mobil tördelését.

## Biztonsági korlátok

- A preview oldalak `noindex,nofollow` és `X-Robots-Tag` védelmet kapnak.
- Az űrlapok review módban nem küldenek adatot.
- A katalógus `containsCustomerData=false` és `runtimeExternalApis=false`
  korlátját a CI ellenőrzi.
- Ár, határidő, garancia vagy vállalás csak jóváhagyott forrásadatból válhat
  éles állítássá; a preview fail-closed figyelmeztetést mutat.
- Nincs automatikus szerződésmódosítás, kötelezettségvállalás,
  felelősségelismerés vagy teljesítésigazolás.
- Titok, credential és ügyféladat nem került a repositoryba.

## Reprodukálás

```bash
python3 scripts/audit-preview-assets.py \
  --base-url http://127.0.0.1:18080 \
  --expected-pages 131 \
  --json-output docs/reports/website-preview-asset-audit-final.json \
  --markdown-output docs/reports/website-preview-asset-audit-final.md
python3 scripts/audit-preview-content.py
npm ci
npx playwright install chromium
PREVIEW_BASE_URL=http://127.0.0.1:18080 npm run test:previews
```

A Playwright minden oldalt 1440×900, 834×1112 és 390×844 méretben nyit meg,
ellenőrzi a konzol- és page errorokat, a sikertelen vagy külső runtime
kéréseket, a 4xx/5xx válaszokat, a törött képeket, a review-navigációt, az
ismétlődő látható szövegblokkokat, a márkakeveredést és a vízszintes
túlcsordulást. Minden nézetről teljes oldalas képernyőkép készül CI-artifactként.

## Credentialök és fennmaradó feladatok

A preview futtatásához **nem szükséges credential**. A Google Drive
fájlazonosítók kizárólag forrásproveniencia-metaadatok; a böngésző nem
kapcsolódik a Drive-hoz. Nincs fennmaradó blokkoló asset-, forrás- vagy
oldalhiány. A 37 külső canonical/navigációs link tartalmi felülvizsgálata
opcionális, runtime függőséget nem jelent.
