# Everyday Homes webtartalom – kötelező kiadási rend

Állapot: `QUARANTINE / REVIEW_REQUIRED`
Publikáció: `publication_allowed = false`

## Kötelező források

- `webszovegiro` skill: célcsoport, ajánlat, természetes magyar nyelv, bizonyítható állítás, etikus konverzió.
- `imperial-conversion-campaign-gate` skill: márkaelkülönítés, direct response minőség, fail-closed kiadás, vizuális renderkapu.
- Everyday Homes kanonikus oldaltérkép: 66 PageID.
- Tulajdonos által jóváhagyott Everyday Homes szövegek és vizuális etalonok.

## Megkerülhetetlen kapuk

1. **Forráskapu:** ár, határidő, technológia, finanszírozás, garancia, referencia és jogi állítás csak azonosított, aktuális forrásból.
   - A számszerű és műszaki állítások útvonal–forrás kapcsolata a `data/claim-evidence.json` fájlban kötelező.
   - Lejárt vagy hiányzó forrásazonosító automatikus `FAIL`; az ellenőrzést a `qa/validate_claim_evidence.py` végzi.
2. **Magyar nyelvi kapu:** természetes mondatszerkezet, egyértelmű alany és állítmány, felolvasva is hétköznapi magyar nyelv. Magyartalan vagy homályos mondat: `FAIL`.
3. **Marketingstratégiai kapu:** az oldal egy valós célpiaci helyzetből indul, konkrét félelmet vagy vágyat old fel, és egy világos következő lépéshez vezet.
4. **Direct response szövegkapu:** a cím érthető és figyelemfelkeltő; a szöveg előnyt, bizonyítékot és cselekvési okot ad. Száraz leírás vagy üres szlogen: `FAIL`.
5. **Márkaőri kapu:** `Otthon – egyszerűen.` és `Kell egy otthon mindenkinek.`; Everyday Homes hang, hivatalos logó és teal–narancs–zsálya–krém paletta. Más Imperial-márka menüje, érvelése, CTA-ja vagy vizuális sablonja nem vehető át.
6. **Vizuális kapu:** desktop, tablet és mobil render; nincs túlcsordulás, levágott szöveg, hibás karakter, alacsony kontraszt vagy külső runtime-asset.
7. **Jogi és pénzügyi kapu:** a kommunikáció nem hozhat létre automatikus ajánlatot, szerződésmódosítást, felelősségelismerést vagy teljesítésigazolást. R6–R7 mindig emberi döntés.
8. **Kiadási kapu:** az exact fájlcsomag SHA-256 hashéhez négy, egymástól független PASS kell: magyar nyelvi szerkesztő, marketingstratéga, direct response szövegíró, márkaőr. A készítő nem hagyhatja jóvá a saját munkáját.
   - A böngészős QA csak automatizált műszaki bizonyíték. Nem helyettesíti a független szövegi vagy tulajdonosi döntést.
   - Kézzel felsorolt, önmagát igazoló PASS-lista érvénytelen. A `qa/qa-evidence.json` ezt fail-closed módon rögzíti.
   - A kiadási jegyzék minden oldala `publication_allowed = false` állapotú marad, amíg ugyanahhoz a hashhez nincs meg az összes kötelező, független jóváhagyás.

## Jelenlegi döntés

Ez a csomag működő távoli staging, de nem kiadási jelölt. A jelenlegi önellenőrzés nem helyettesíti a négy független döntést; ezért a publikációs státusz változatlanul blokkolt.
