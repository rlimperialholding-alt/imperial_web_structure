# Kalkulátorok, HouseMatch és BuildConfig – as-built

## Új építés

A publikus kalkulátor a `Kalkuláció_oldalakhoz_frissített_minden_weboldal_2026-07.xlsx` márka- és technológiai alapárait szorozza a meglévő átadási állapot / műszaki csomag tényezőkkel. Nem tartalmaz belső önköltséget.

A belső végpont ugyanezt az eredményt összeveti az `Imperial_100m2_Technologia_Keszultseg_Armodell_2026_07.xlsx` cash-költség, minimum, optimum és piaci plafon értékeivel, és kiszámítja a 35%-os cash-margin kaput.

## Felújítás

A tételkereső közvetlenül a `Generalkivitelezo_ArTukor_Munkadij_Anyag_2026_07.xlsx` 398 munkadíj- és 283 anyagtételét használja. A kiválasztott mennyiségek nettó, bruttó és helyszíni feltárás előtti felső becslési sávot adnak.

## HouseMatch

A `HouseMatch_catalog_score_v0.1.xlsx` 45 aktív háza és eredeti négy profilja változtatás nélkül került bekötésre. A pontszám összetevői: ár, alapterület, élethelyzet és márka.

## BuildConfig

A webes nézet nem külön árképző rendszer. A konfiguráció a közös kalkulációs végpontot használja, és megtartja a BuildConfig v0.2 üzleti kapuit: műszaki, pénzügyi, fedezeti, cashflow- és kapacitásjóváhagyás.

## Következő élesítési feladatok

- márkánkénti saját CSS/design token és beágyazási útvonal;
- HouseMatch/BuildConfig média- és alaprajz-CDN;
- CRM webhook és konfigurációverzió tárolása;
- tíz lezárt projektes ár-visszamérés;
- valós kapacitáslimit és pénzügyi forrásgazda jóváhagyása.
