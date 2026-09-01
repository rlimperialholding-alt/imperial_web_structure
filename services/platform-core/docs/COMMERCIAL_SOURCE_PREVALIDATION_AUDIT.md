# Kereskedelmi forrás-elővalidáció – audit és szabályzat

Audit dátuma: 2026-07-26

## Döntés

A hét márka aktuális weboldalán publikált kereskedelmi ajánlat, USP, árközlés,
műszaki tartalom, jogi vagy szerződéses tájékoztatás elővalidált forrásnak
minősül. Emberi tartalmi jóváhagyás nélkül kizárólag változatlan, forráshoz
kötött marketingkommunikációban használható.

Ez a szabály nem engedélyez automatikus jogi aktust. Külső
kötelezettségvállalás, szerződésmódosítás, felelősségelismerés és
teljesítésigazolás továbbra is kötelező emberi R6–R7 művelet.

## Weboldalaudit

A crawler 7 domain 840 oldalát vizsgálta, márkánként legfeljebb 120 releváns
oldallal; ezek közül 762 adott használható HTTP 200 HTML-választ. A verziózott
registry 3 918 egyedi, normalizált forrásfragmentumot és 5 062 típusház-,
házmodell- vagy alaprajz-asset referenciát tartalmaz.

A 78 kizárt válasz 61 darab 404-es és 17 darab 500-as oldalból állt. Ezek
egyetlen állítása vagy assetje sem kaphat automatikus forrás-elővalidációt. A
Prefabnál mért 44 darab 404 külön webhely-karbantartási tétel; nem lazítja a
Copy Gate szabályát.

| Márka | Vizsgált / HTTP 200 | Fragmentum | Vizuális referencia | Aktív Drive-árazás |
|---|---:|---:|---:|---|
| Imperial Holding | 120 / 118 | 1 436 | 528 | igen |
| Bautica | 120 / 109 | 529 | 754 | igen |
| Prefab | 120 / 76 | 695 | 449 | igen |
| Danish Fabrik | 120 / 117 | 307 | 1 000 | igen |
| BauFreund | 120 / 114 | 407 | 715 | igen |
| Casa Moderna | 120 / 114 | 206 | 643 | még nincs |
| TimberHaus | 120 / 114 | 338 | 973 | még nincs |

Kiemelt, megtalált és használható üzenetek:

- Imperial Holding: „FIX MINŐSÉG, FIX ÁR, FIX HATÁRIDŐ”, a „Miért választanak
  minket?” bizonyítékblokkok, valamint a négy pillér/érték közül a
  kockázatmentes építkezés, egy kézben vezetett folyamat, választék és stabil
  céges háttér.
- Prefab: fix ár, határidő és minőség; 60 napos tervezés, 120–180 napos
  kivitelezés; 180 napon belüli, kötbérrel vállalt kulcsrakész átadás.
- BauFreund: a megrendelő érdekében dolgozó külsős, független műszaki ellenőr
  mint minőségi referenciapont.
- Bautica: fix ár, fix határidő, árgarancia és az ezekhez tartozó szerződéses
  feltételek.
- Danish Fabrik, Casa Moderna és TimberHaus: a jelenlegi műszaki rétegrendek,
  technológiai tartalmak, határidő- és garanciafeltételek.

## Árforrások

Automatikusan publikálható ár kizárólag a
`Kalkuláció_oldalakhoz_frissített_minden_weboldal_2026-07.xlsx` kanonikus
Drive-forrás és a repository kalkulátorának pontos egyezése esetén áll elő.

- Drive file ID: `1pFiXUVRIOqkDf40pgM5jUgNX2gUHpxZ4`
- SHA-256:
  `D5F69604709882BA6469ECAAF1BE2A622328C6E896E2DA572260F50BB782CABC`
- Aktív márkák: Imperial, Bautica, Prefab, Danish Fabrik, BauFreund.
- Kötelező egyezés: márka, technológia, készültségi szint, csomag, bruttó
  alapterület, áfakulcs, output mező, forintösszeg és kommunikált feltételek.

Casa Moderna és TimberHaus automatikus árpublikációja fail-closed marad, amíg
nem kerül hozzájuk jóváhagyott, verziózott árforrás a registrybe.

Az `Imperial_100m2_Technologia_Keszultseg_Armodell_2026_07.xlsx` belső
kontrollforrás. A `Haz_Ar_Web` lap „JAVASOLT” jelölése miatt közvetlen
automatikus publikálásra nem használható. Az Offer Matrix javaslatai szintén
ki vannak zárva, mert aktiválást igényelnek és nem élő ajánlatok.

## Fail-closed illesztési szabályok

1. Webes állításnál egyeznie kell a márkának, snapshotverziónak,
   forrás-URL-nek, normalizált szövegnek, SHA-256 hashnek és kategóriának.
2. A közölt claimnek a forrásfragmentum pontos részletének kell lennie.
3. Típusházképnél vagy alaprajznál egyeznie kell a márkának, forrásoldalnak,
   asset-URL-nek és a registry referenciahashének.
4. Drive-árnál futás közben újraszámoljuk az árat; bármely eltérés blokkol.
5. Új vagy átírt tényszerű állítás, nem regisztrált vizuál, hiányzó árfeltétel,
   megváltozott forrás vagy ismeretlen márka nem kap elővalidációt.
6. Publikáláskor a bizonyítékot újraellenőrizzük, és a forrásregistry
   verzióját, hashét, evidence ID-ket és kalkulátor-inputot auditáljuk.

## Biztonsági határ

A weboldalon már szereplő szerződéses vagy jogi mondat újraközlése
marketingkommunikáció. Nem jelent új ajánlat elfogadását, egyedi
kötelezettségvállalást vagy szerződéses nyilatkozatot. Az R4–R7 kockázati szint,
illetve a nem `marketing_communication` művelettípus automatikusan kizárja a
forrás-elővalidációt; R6–R7 mindig emberi jóváhagyású.

## Implementáció

- Registry:
  `app/static/prevalidated-commercial-sources/manifest.json`
- Registry-generátor:
  `scripts/build_prevalidated_commercial_registry.py`
- Determinisztikus validátor:
  `app/services/commercial_prevalidation.py`
- Migráció:
  `alembic/versions/20260726_0008_commercial_source_prevalidation.py`
- Regressziós tesztek:
  `tests/test_commercial_prevalidation.py`
