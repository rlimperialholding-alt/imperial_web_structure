# Weboldalak preview — teljes asset- és böngészőaudit

Dátum: 2026-07-25
Ág: `feature/platform-foundation`

## Eredmény

- Katalógus: **70 oldal / 12 márka** (az eredeti 50 oldal és 20, Drive-forrásból
  visszaállított vagy előállított tényleges preview).
- Statikus és HTTP asset-audit: **0 blokkoló hiba**, **791 sikeres helyi
  függőség**.
- Külső runtime kérés: **0**.
- Külső navigáció vagy forrás-metaadat: **37**; ezeket a böngésző nem tölti be
  oldalfüggőségként.
- Hiányzó katalógusoldal: **0**.
- Playwright-mátrix: **211/211 sikeres** (**70 × 3 nézetméret + 1
  katalógusteszt**), helyi futásidő 6,1 perc.

| Kért hibakategória | Végleges darabszám |
|---|---:|
| HTTP 404 / nem 200 helyi függőség | 0 |
| Blokkolt külső runtime függőség | 0 |
| Nem létező helyi fájl | 0 |
| Hibás relatív vagy abszolút útvonal | 0 |
| Márkaspecifikus, közös `/assets/` hivatkozás | 0 |

Az audit minden HTML `href`, `src`, `srcset`, inline `style`, CSS `url()` és
`@import`, valamint statikus JavaScript `import`/dinamikus `import()` hivatkozást
rekurzívan követ. A katalógusoldalak és minden helyi függőség fájlrendszeren,
majd HTTP-n is ellenőrzésre kerül.

## Kiinduló állapot és javítás

Az eredeti 50 oldalas baseline 136 blokkoló hibát tartalmazott. Mind a 136
márkaspecifikus fájl közös `/assets/` névtérre mutató hivatkozás volt:

| Márka | Baseline oldal | Baseline hiba | Javítás |
|---|---:|---:|---|
| Imperial Holding | 10 | 31 | tokenek, komponensek, saját CSS/JS/adat és teljes Bootstrap helyi csomagolása |
| Bautica | 6 | 18 | teljes Bootstrap, Bootstrap Icons és review assetek márkakönyvtárba helyezése |
| Prefab | 19 | 42 | teljes Bootstrap, Bootstrap Icons és review assetek márkakönyvtárba helyezése |
| Budapesti Magasépítő Vállalat | 15 | 45 | teljes Bootstrap, Bootstrap Icons és review assetek márkakönyvtárba helyezése |

A Bootstrap 5.3.3 teljes minifikált CSS-e és bundle JavaScriptje, valamint a
Bootstrap Icons 1.11.3 CSS- és fontfájljai az érintett márkák saját
`assets/vendor/` könyvtárában találhatók, licencfájlokkal együtt. A korábbi
részleges kompatibilitási réteg nincs bekötve a preview-kba.

A hét dokumentumforrásos márka valódi Drive-specifikációja
`source/website-spec.md` alatt maradt meg, és abból reprodukálható,
márkaspecifikus, nem helyőrző oldal készült. A Family Homes Drive-csomagjának
mind a 13 teljes HTML-oldala bekerült.

## Márkánkénti állapot

| Márka | Elérhető | Hiányzó | Ellenőrzött helyi hivatkozás | Javított assetek | Fennmaradó blokkoló probléma |
|---|---:|---:|---:|---|---|
| Imperial Holding | 10 | 0 | 78 | 31 útvonal; saját közös és vendor csomag | nincs |
| Danish Fabrik | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |
| Bautica | 6 | 0 | 42 | 18 útvonal; teljes Bootstrap/Icons | nincs |
| Prefab | 19 | 0 | 74 | 42 útvonal; teljes Bootstrap/Icons | nincs |
| Casa Moderna | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |
| Family Homes | 13 | 0 | 223 | 13 oldal; teljes Bootstrap/Icons és review assetek | nincs |
| Everyday Homes | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |
| Property 360 | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |
| Budapesti Magasépítő Vállalat | 15 | 0 | 318 | 45 útvonal; teljes Bootstrap/Icons | nincs |
| BauFreund | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |
| RED Property | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |
| Timberhaus | 1 | 0 | 8 | helyi CSS, JS, SVG, Inter font | nincs |

## Navigáció és reszponzivitás

A márkán belüli linkeket a helyi review bridge a
`/site-preview/<brand>/...` névtérben tartja, és `review=1` módban a query
paramétert minden belső navigáción megőrzi. A teszt ezt az oldal betöltése után
az összes belső anchoron ellenőrzi.

Az importált Bootstrap-fragmentumok közvetlen, konténer nélküli `.row`
elemeinek negatív gutter margója mobilon 12 pixeles vízszintes kilógást okozott.
A márkánként másolt review-stílus célzott, `575.98px` alatti korrekciója ezt
megszünteti anélkül, hogy a desktop vagy tablet elrendezést módosítaná.

## Biztonsági korlátok

- Minden runtime asset same-origin és márkaspecifikus.
- Nincs CDN-, Google Fonts-, külső kép-, ikon- vagy JavaScript-függőség.
- A CSP same-originra korlátozza az asseteket és kapcsolatokat.
- Minden oldal `noindex,nofollow`, az nginx `X-Robots-Tag` fejlécet is ad.
- Az importált űrlapok tesztmódban nem küldenek adatot.
- Az adatkatalógus `containsCustomerData=false` és
  `runtimeExternalApis=false` korlátját a CI ellenőrzi.
- Titok, credential és ügyféladat nem került a repositoryba.

## Reprodukálás

```bash
python3 scripts/audit-preview-assets.py \
  --base-url http://127.0.0.1:8080 \
  --expected-pages 70 \
  --json-output reports/website-preview-asset-audit.json \
  --markdown-output reports/website-preview-asset-audit.md
npm ci
npx playwright install chromium
PREVIEW_BASE_URL=http://127.0.0.1:8080 npm run test:previews
```

A Playwright minden oldalt 1440×900, 834×1112 és 390×844 méretben nyit meg,
ellenőrzi a konzolhibákat, page errorokat, sikertelen vagy külső runtime
kéréseket, 4xx/5xx válaszokat, törött képeket, review-navigációt és vízszintes
túlcsordulást. A 210 képernyőkép CI-artifactként kerül megőrzésre.

## Credentialök és fennmaradó feladatok

A preview futtatásához **nem szükséges credential**. A Google Drive
fájlazonosítók kizárólag forrásproveniencia-metaadatok; a böngésző nem kapcsolódik
a Drive-hoz. Nincs fennmaradó blokkoló asset- vagy oldalhiány. A 37 külső
canonical/navigációs link tartalmi felülvizsgálata opcionális, runtime függőséget
nem jelent.
