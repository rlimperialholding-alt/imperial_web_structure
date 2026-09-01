# Changelog

## 1.42.2 – Imperial Care jogosultság- és integritáskapuk

- Az ügyféltől elrejtett belső megjegyzéseket az ügyhöz rendelt alvállalkozó sem láthatja; csak a kijelölt belső Imperial Care szerepkörök férnek hozzájuk.
- A bizonyítékfájl letöltése ismét ellenőrzi a tárolt SHA-256 értéket, és eltérés esetén fail-closed 409 választ ad.
- A státuszváltás sorzárral és kötelező ügyverzióval védett, ezért két párhuzamos munkatárs nem írhatja felül észrevétlenül egymás döntését.
- Elutasítás csak részletes indoklással rögzíthető, felelősnek érvényes e-mail kell, lezárt vagy elutasított ügyben pedig nem módosítható az üzenet- és bizonyítéklánc.
- A munkasor projekt, állapot, súlyosság, felelős és szabad szöveg szerint szűrhető; az Imperial Care/MyImperial kapcsolódás 16 célzott tesztje sikeres.

## 1.42.1 – PlanCheck feltöltési életciklus és műszaki munkasorok

- A PlanCheck ügyfélfeltöltési hivatkozása auditáltan, 7–90 napos érvényességgel újra kiadható; a korábbi link azonnal érvénytelenné válik, az aktív link pedig külön visszavonható.
- A PlanCheck részletképernyő mutatja a link állapotát és lejáratát anélkül, hogy a titkos token visszaolvasható lenne.
- A PlanCheck, HouseBuild és PlotCheck munkasor projekt, állapot és szabad szöveg szerint szűrhető, a csak megtekintési jogú felhasználó pedig nem kap megtévesztő létrehozási űrlapot.
- A három kanonikus műszaki modul 25 célzott üzleti és képernyőtesztje elkülönített adatbázison sikeresen lefutott.

## 1.41.0 – Canonical BuildConfig engine

- A BuildConfig saját ügy-, megváltoztathatatlan verzió-, BOM-, validáció- és tízkapus adatmodellt kapott; a korábbi generikus műszaki BuildConfig írási út csak olvasható.
- Minden konfiguráció kiválasztott, azonos ProjectID-jú HousePlanhoz, a három kalkulációs forrás SHA-256 pillanatképéhez és verziózott vállalati policyhez kötött.
- Tételes alap- és opció-BOM, opciókompatibilitás, nettó ár/önköltség, minimumfedezet, mérföldkő-cashflow, brigád- és határidőkapacitás készül fail-closed automatikus kapukkal.
- A műszaki és pénzügyi kaput két külön név szerinti ellenőr hagyja jóvá; a készítő nem reviewzhat és nem adhatja ki saját verzióját.
- Kiadáskor SHA-256 ellenőrzött PDF és `CONFIGURATION_APPROVED` esemény készül a HouseBuild, Sales, Reservation, Contract, Finance, Procurement, Project Control, CRM és MyImperial felé.
- Idempotens éles UAT-seed és külön séma/hash/PDF-invariáns ellenőrző készült.

## 1.40.0 / Platform 5.0.0 - 2026-08-03

- A HouseBuild külön, kanonikus HousePlan-generáló és -kiadó üzleti motort, valamint teljes munkateret kapott; a korábbi általános HouseBuild adatlap csak olvasható.
- Kizárólag aktív, kiadott és tartalom-hash-sel azonosított House Catalog verzió, valamint hivatkozással és SHA-256-tal kötött felhasználásijog-bizonyíték használható.
- Három tartós HousePlan-változat készül saját helyiségprogrammal, kapcsolati gráffal, befoglaló geometriával, geometry signature-rel, költségbecsléssel és változtathatatlan tartalom-hash-sel.
- Változatonként területkonzisztencia-, méret-, helyiségminimum-, topológia- és katalógushűség-validáció fut; hibás jelölt megtekinthető, de nem küldhető tovább.
- A kiválasztott változathoz nyolc fail-closed kapu tartozik: forrás/jog, program, duplikáció, topológia, PlotCheck, BuildConfig, PlanCheck és műszaki jóváhagyás.
- A PlotCheck, BuildConfig és PlanCheck csak azonos ProjectID-val és megfelelő végállapotban kapcsolható; automatikus kapu kézzel nem írható felül.
- Kiadáskor négy szem elv, SHA-256 ellenőrzött PDF és House Catalog/HouseVision/HouseMatch/BuildConfig/PlanCheck/CRM/MyImperial/Engineering/Contract Generator outbox-esemény készül.
- Idempotens kiadott és duplikációs STOP UAT-forgatókönyv, integritás-ellenőrző és Alembic `20260803_0047`.

## 1.39.0 / Platform 5.0.0 - 2026-08-03

- A PlotCheck külön, kanonikus CHK-ENG-002 üzleti motort és teljes munkateret kapott; a korábbi általános PlotCheck adatlap csak olvasható.
- Verziózott önkormányzati/övezeti szabálytár működik draft, verified, demo, elkülönített UAT és retired életciklussal; demo/UAT forrás normál ügyben fail-closed módon tiltott.
- GeoJSON Polygon vagy téglalap telekgeometria, SHA-256 pillanatkép, Shapely építésihely-, 0°/90° házelhelyezés-, beépítettség-, szintterület-, magasság-, zöldfelület- és rendeltetésvizsgálat.
- Kilenc kötelező, hash-kötött szakági bizonyíték és nyolc jóváhagyási kapu; a forrás feltöltője saját bizonyítékát nem hitelesítheti.
- Csak `FIT`, `FIT WITH CONDITIONS`, `RE-DESIGN REQUIRED` vagy `NOT SUITABLE` eredmény adható; hiányzó vizsgálat STOP feltétel, minden feltételhez teljes ActionID, költség-, határidő- és tervezési hatás szükséges.
- Minden változás elavulttá teszi a korábbi számítást; lezáráskor négy szem elv, SHA-256 ellenőrzött PDF és CRM/MyImperial/HouseBuild/BuildConfig/Engineering outbox-esemény készül.
- Három idempotens, elkülönített UAT forgatókönyv és Alembic `20260803_0046`.

## 1.38.0 / Platform 5.0.0 - 2026-08-03

- A közös outbox szimulált sikere megszűnt: belső modul csak tartós, idempotens inbox-receipt és SHA-256 payload-kötés után kaphat `sent` állapotot.
- A korábban bizonyíték nélkül `sent` állapotba került történeti üzenetek a migrációkor automatikusan visszakerülnek valódi kézbesítési sorba.
- A történeti modulaliasok a 47 elemű kanonikus modulregiszterre oldódnak fel; ismeretlen cél és sérült payload fail-closed módon hibára fut.
- A külső adaptercélok igazolt adapter-receipt nélkül nem jelölhetők kézbesítettnek, hanem visszatérő próbálkozásba, majd dead-letter állapotba kerülnek.
- A platform háttérmunkása 15 másodperces outbox-ciklussal külön, újrainduló konténerként fut; a konzisztenciaellenőrzés ettől elkülönítve óránként fut.
- Alembic `20260803_0045` és külön inbox/outbox integritás-ellenőrző.

## 1.37.0 / Platform 5.0.0 - 2026-08-03

- A PlanCheck külön, kanonikus v0.1 üzleti motort és teljes belső/ügyfél képernyőkészletet kapott.
- Tokenvédett, 30 napos ügyfélfeltöltés; PDF/JPG/PNG/DOCX/XLSX/IFC/DWG formátum-, magic-byte-, méret-, SHA-256- és tartalmi ellenőrzés.
- Minden dokumentum- vagy feltételezésváltozás új, változtathatatlan revíziót nyit, és érvényteleníti az előző jóváhagyásokat.
- Automatikus A–D bizalmi osztály és hiánylista; magas hatású nyitott EA blokkolja a kiadást.
- Öt elkülönített kapu (input, engineering, commercial, finance, executive), külön jóváhagyókkal és négyszem-elvvel.
- Csak `SENDABLE` vagy `NOT SENDABLE` végeredmény; a kiadható döntés fail-closed, SHA-256 ellenőrzött PDF-jelentést készít.
- Alembic `20260803_0044`.

## 1.36.0 / Platform 5.0.0 - 2026-08-03

- A Contract Generator platformadapter verziója `0.6.0`.
- A generált szerződéscsomag tartós, auditált életciklusrekordot kap a kanonikus payload és dokumentumok SHA-256 kötésével.
- Elkülönített kereskedelmi, műszaki, szükség szerint jogi és vezetői jóváhagyási kapuk; a készítő és a kapuk jóváhagyói nem lehetnek azonos személyek.
- Az aláírt példány bizonyítékazonosítója és hash-e, valamint a postai és elektronikus kézbesítés bizonyítékai kötelezőek.
- A munkakezdés minden kapu lezárásáig fail-closed; a `CONTRACT_SIGNED` esemény csak a kettős kézbesítés utáni aktiváláskor jön létre.
- A közvetlen, életciklust megkerülő aláírt-státusz API lezárult.
- Alembic `20260803_0043` és külön szerződés-életciklus séma/integritás-ellenőrző.

## 1.35.0 / Platform 5.0.0 - 2026-08-03

- A szerződésgenerátor nyers JSON-mezője helyett öttípusos, csoportosított üzleti adatbeviteli képernyő működik.
- A ProjectID, CRM-azonosítók, felek, projekt, ár, fizetési ütem, határidők és biztosítás külön validált mezőket kaptak.
- Minden kötelező melléklethez Drive- vagy dokumentumbizonyíték szükséges; bizonyíték nélküli csomag fail-closed módon blokkolódik.
- A nettó díjból és áfakulcsból a rendszer számolja az áfa- és bruttó összeget, a fizetési ütemnek pedig pontosan 100%-ot kell kiadnia.
- A generálás nem állít be hamis üzleti jóváhagyást: a kereskedelmi és műszaki kapu `PENDING` állapotból indul.

## 1.34.0 / Platform 5.0.0 - 2026-08-03

- A generált szerződéscsomagok a konténercserét túlélő platform-runtime kötetre kerülnek.
- A szerződésartifactok letöltése moduljogosultsághoz, engedélyezett tárolási gyökérhez és SHA-256 integritás-ellenőrzéshez kötött.
- A platformmentés az immutable forrásadatok mellett a teljes perzisztens runtime-fát is tartalmazza.
- A visszaállítási próba külön ellenőrzi a platform adat- és runtime-archívum szerkezetét.

## 1.33.1 / Platform 5.0.0 - 2026-08-03

- Az Answer Center szintetikus jóváhagyási eseménye kizárólag bejegyzett platformmodulokhoz kézbesít.
- Automatikus regressziós kapu tiltja az ismeretlen fogyasztót tartalmazó modulműveleteket.

## 1.33.0 / Platform 5.0.0 - 2026-08-03

- Célrendszerenként auditált, idempotens publikációs kézbesítési életciklus a Content Factory kimeneteihez.
- Rövid foglalási idővel védett adapter-claim, payload-hash kötésű receipt és változtathatatlan sikeres visszaigazolás.
- Exponenciális újrapróbálás, holtlevél-kezelés, jogosultságvezérelt kézi újraindítás és operátori felület.
- A karanténba helyezett tartalom visszavonási céljai korábbi kézbesítésből vagy a jóváhagyott exportcsomagból állnak helyre.
- Alembic `20260803_0042`.

## 1.32.0 / Platform 5.0.0 - 2026-08-02

- A marketinghozzájárulás teljes, auditált életciklust kapott: belső engedélyezés és visszavonás, valamint személyes önkiszolgáló leiratkozási hivatkozás.
- A visszavont e-mail-cím automatikusan a közös küldési tiltólistára kerül; más tiltási okot a rendszer nem ír felül.
- A visszavonást követő egyszerű duplikált leadjel fail-closed módon nem engedélyezheti újra a marketingküldést.
- A hozzájárulási állapot a kanonikus CRM-rekordba és a CRM üzleti rekordjába is szinkronizálódik.
- Alembic `20260802_0041`.

## 1.31.0 / Platform 5.0.0 - 2026-08-02

- Devizánként elkülönített cash-flow előrejelzés; árfolyamforrás nélkül nincs tiltott devizaösszeadás.
- Típusbiztos projektpénzügyi összesítések és teljes finance lint/mypy kapu.
- A benyújtó, pénzügyi ellenőr és vezetői jóváhagyó kötelező személyi elkülönítése.
- Kanonikus pénzügyi tételek átbesorolása kizárólag pénzügyi jogosultsággal és auditnaplóval.
- A teljes bejövőszámla- és besorolási állomány olvasása pénzügyi/vezetői szerepkörre korlátozva.
- Projektenként egyetlen nyitott pénzügyi terv adatbázis-szintű kikényszerítése.
- Alembic `20260802_0040`.

## 1.30.0 / Platform 5.0.0 - 2026-08-02

- Hét dimenziós, verziózott és súlyozott partner-teljesítmény scorecard a TPL-PART-001 szerint.
- Lejárt partner-újraminősítés és lejárt vagy még nem hatályos döntés fail-closed blokkolása.
- Ismétlődő súlyos incidensek automatikus felfüggesztése és dokumentált korrekciós lezárási kapu.
- Felfüggesztett vagy kizárt partner csak elkülönített PM, pénzügyi/jogi és vezetői reinstatement review, lezárt súlyos incidensek, majd külön visszaengedélyezési döntés után válhat újra alkalmassá.
- Alembic `20260802_0039`.

## 1.29.1 / Platform 5.0.0 - 2026-08-02

- Projektkiosztások auditált visszavonása a DPM operátori munkatérből.
- A legfrissebb aktív projektkiosztás determinisztikus megnyitása.

## 1.29.0 / Platform 5.0.0 - 2026-08-02

- Szerepkörös Digital Project Managers operátori munkatér a platform munkamenetéből.
- Rövid életű, projektkörre szűkített szolgáltatás-tokenek és fail-closed DPM gateway.
- Projektkiosztás, R0-R7 feladatkapu, jóváhagyás, projektmemória, tudástár és audit felhasználói képernyőn.
- R4-R5 feladatok emberi jóváhagyás utáni újrasorba állítása és végrehajtása.

## 1.28.0 / Platform 5.0.0 - 2026-08-02

- Live, belso tokennel vedett kanonikus projekt- es felhasznalo-read API a Digital Project Managers szolgaltatasnak.
- A DPM projektkontextus megszunteti a production `platform.json` prototipus-fuggest.
- Brand SVG kiadasi archivumok kotelezo LF-normalizalasa a SHA-256 integritas megorzesehez.

## 1.21.0 – 2026-08-02

- natív Project Control jóváhagyott, SHA-256-tal zárolt scope-, ütem- és Finance-baseline-nal;
- kanonikus Operations/Finance/ChangeControl terv–tény–EAC forecast és automatikus eltérésképzés;
- kötelező gyökérok, recovery-akció, független teljesítés-verifikáció és 35%-os fedezeti vörös vonal;
- TPL-OPS-012 heti vezetői státuszriport, feladat- és vezetői eseményprojekció;
- elkülönített PM, műszaki, pénzügyi és vezetői jóváhagyási kapuk;
- szerepkörös kezelőfelület, API, idempotens szerver-UAT és sémaellenőrzés;
- Alembic `20260802_0032`.

## 1.20.0 – 2026-08-02

- natív Engineering Workspace a 3 napos konzultációs és abszolút 90 napos tervezési kapuval;
- szakági deliverable-jegyzék, változtathatatlan dokumentumverziók és SHA-256 bizonyíték;
- független tervreview, kiadás, blokkoló finding és új revízióhoz kötött feloldás;
- visszaigazolt transmittal-csomag és fail-closed construction-ready ellenőrzés;
- szerepkörös kezelőfelület, API, idempotens szerver-UAT és sémaellenőrzés;
- Alembic `20260802_0031`.

## 1.9.2 – 2026-08-01

- CRM- és ITEP-tulajdonú kanonikus rekordok visszhangmentes, egyirányú beolvasása;
- Platform-tulajdonú rekordok kétirányú, 10-es időtűrő CRM-kézbesítése;
- privát Sites CRM célváltás utáni kanonikus egyeztetés támogatása.

## 1.1.0 / Platform 4.4.0 – 2026-07-19

- Enterprise Import Center adatmodell és reszponzív adminfelület;
- pénzügyi, projekt-, partner-, ügyfél-, beszerzési, szerződéses és termékadat-osztályozás;
- staging, validáció, deduplikáció, emberi jóváhagyás, commit és rollback;
- CSV/JSON/XLSX/TXT kézi import;
- connector push API Gmail/Drive/Sheets adapterekhez;
- ProjectID és ProjectFact integráció;
- 2026-07 jóváhagyott kalkulációs források zárolása Drive ID-val és SHA-256-tal;
- újépítési és felújítási kalkulátor API és webes felület;
- HouseMatch eredeti katalógus és pontozás webes/API bekötése;
- BuildConfig vizuális konfigurációs felület;
- TenderMail kampány-, címzett-, domainhitelesítési, suppression- és kézbesítési réteg;
- éles provider nélküli biztonságos küldésszimuláció;
- Alembic 20260719_0002;
- 29/29 automatizált teszt.

## 1.0.0 – 2026-07-19

- 15 modulos modulregiszter és heartbeat;
- közös ProjectID-, esemény-, objektum- és feladatvetület;
- idempotens event gateway;
- outbox/retry/dead-letter;
- hét rendszerközi konzisztenciaszabály;
- tulajdonosi/ügyvezetői kivételcockpit;
- release, artifact, environment és deployment kapuk;
- három szintetikus E2E integrációs pilot;
- PostgreSQL/Docker production alap;
- Alembic 20260719_0001;
- 20/20 automatizált teszt.

## 1.2.0 / Platform 4.7.0 – Workspace v1.0
- Közös Imperial Intelligence app shell és oldalsó navigáció.
- Személyes Workspace kezdőlap.
- Action Center feladatkezelés és auditált állapotváltás.
- Projekt 360° közös ProjectID nézet.
- Központi dokumentumtár és `ws_documents` modell.
- Csoportosított központi kereső.
- 3 új Workspace automatizált teszt; teljes eredmény 32/32.

## 1.5.0 / Platform 5.0.0 – Commercial Integration v1.0

- kötelező „reuse first / no duplicate development” discovery gate;
- minden kiadás előtt Drive-, modul-, release- és forrásartifact-ellenőrzés;
- új kiadás `discovery_blocked`, ha nincs jóváhagyott újrafelhasználási vagy kivételi döntés;
- a Contract Generator v0.4 kanonikus, Drive-ról visszaellenőrzött forráscsomagjának változtatás nélküli adapteres bekötése;
- a Contract Generator ZIP és mind az öt master sablon SHA-256 ellenőrzése minden generálás előtt;
- szerződéscsomagok Workspace-dokumentumtári regisztrációja és Contract Generator projektállapot-projekció;
- ugyanazon szerződésszám csendes újbóli generálásának blokkolása;
- ChangeControl v0.1 esemény- és állapotprojekció új ár-, fedezet-, scope- vagy jóváhagyási motor nélkül;
- közös Commercial Integration és Development Governance webes felület;
- Alembic `20260719_0006`;
- 80/80 alkalmazásteszt és a kanonikus Contract Generator további 15 résztesztje sikeres.
