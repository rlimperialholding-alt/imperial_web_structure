IMPERIAL INTELLIGENCE
SZÖVEG-, DIRECT RESPONSE COPYWRITING- ÉS PUBLIKÁCIÓS KAPURENDSZER v1.0


Kötelező fejlesztési, tartalomgyártási és minőségbiztosítási szabvány


1. VEZETŐI DÖNTÉS


Az Imperial Intelligence rendszerben a szöveg nem dekoráció és nem kitöltendő mező. A szöveg az elsődleges értékesítési motor. Weboldal, landing oldal, hirdetés, e-mail, chatbot, ajánlat, kampány, közösségi média, videószkript és automatizált üzenet csak akkor tekinthető késznek, ha a szöveg egyszerre:


• márkaspecifikus;
• természetes, erős magyar nyelvű;
• direct response szemléletű;
• konkrét üzleti ajánlatot közvetít;
• bizonyítékokra épül;
• kifogást kezel;
• egyértelmű következő lépésre vezet;
• nem tartalmaz üres, sablonos vagy AI-s megfogalmazást;
• megfelel a kanonikus márka-, claim-, ár-, ajánlat- és jogi forrásoknak.


A rendszer nem publikálhat olyan szöveget, amely pusztán helyes, informatív vagy esztétikus. A minimumszint: professzionális magyar online értékesítési szöveg, amely stratégiai gondolkodásban, ajánlatépítésben, ritmusban, figyelemvezetésben, kifogáskezelésben és konverziós fegyelemben a legerősebb hazai direct response copywriting színvonalához mérhető.


A jelen dokumentum nem új márkastratégiát hoz létre. A már elkészült márkakézikönyvek, magyar márkamaszterek, Full Design System, SEO/AEO csomagok, Brand Profiles, aktív PriceSnapshot-, OfferVersion-, TermsVersion- és ClaimID-rekordok fölé épít kötelező szöveg-végrehajtási és publikációs kapurendszert.


2. A HIBA VALÓDI OKA


A rendszer jelenleg valószínűleg hozzáfér a szabályokhoz, de nem kényszerül azok teljes alkalmazására. A generáló modell több dokumentumból részleges kontextust kap, majd szabadon fogalmaz. Emiatt:


• általános építőipari szövegek születnek;
• a márkák hangja összemosódik;
• a szlogen, ajánlat, ár és bizonyíték nem alkot egységet;
• a szöveg tájékoztat, de nem értékesít;
• a címsorok nem visznek tovább;
• a nyitás nem teremt érdeklődést vagy feszültséget;
• az előnyök helyett tulajdonságlisták jelennek meg;
• a kifogások és kockázatok nincsenek kezelve;
• a CTA-k általánosak;
• a rendszer elfogad nyelvtanilag helyes, de üzletileg gyenge szöveget.


A javítás kulcsa: a szövegalkotást nem egyetlen prompttal kell irányítani, hanem strukturált ajánlati bemenettel, kötelező copy-architektúrával, külön kritikusi ellenőrzéssel, mérhető minőségi kapukkal és fail-closed publikációval.


3. KANONIKUS FORRÁSHIERARCHIA


Minden szöveggenerálás előtt a rendszer kötelezően feloldja és verzióval rögzíti:


1. jóváhagyott magyar márkamaszter;
2. márkaspecifikus arculati és konverziós kézikönyv;
3. Brand Profile és célcsoport-profil;
4. oldal- vagy kampánycél;
5. aktív ajánlati rekord;
6. aktív ár-, határidő- és feltételrekord;
7. jóváhagyott claim- és bizonyítékrekord;
8. termék-, ház- vagy szolgáltatásadat;
9. SEO/AEO oldalcsomag;
10. csatornaspecifikus formai szabály;
11. korábban jóváhagyott, magas teljesítményű szövegminták;
12. tiltott és elhasznált megfogalmazások listája.


A build vagy kampányfutás nem indulhat el, ha a kötelező források közül bármelyik hiányzik, lejárt vagy ellentmondásos.


4. KÖTELEZŐ COPY BRIEF ADATMODELL


Az AI nem kaphat olyan nyitott utasítást, hogy „írjon jó szöveget”. Minden feladat kötelező CopyBrief rekordból indul.


Kötelező mezők:


• CopyBriefID
• BrandID
• AssetType
• Channel
• PageID vagy CampaignID
• CampaignObjective
• PrimaryConversion
• TargetPersonaID
• AwarenessLevel
• MarketSophisticationLevel
• CoreProblem
• DesiredOutcome
• PrimaryPromise
• UniqueMechanism
• OfferVersionID
• PriceSnapshotID
• TermsVersionID
• ClaimIDs
• ProofIDs
• HousePlanID vagy ProductID
• PrimaryObjectionIDs
• SecondaryObjectionIDs
• RiskReversal
• UrgencyReason
• ScarcityReason
• PrimaryCTAType
• SecondaryCTAType, ha engedélyezett
• BrandVoiceProfile
• RequiredSloganVersion
• ForbiddenPhrases
• RequiredKeywords
• LandingMessageMatchID
• ValidFrom
• ValidUntil


Hiányos briefből szöveg nem készülhet. A rendszer kérdéslistát vagy hibajegyet ad vissza, nem talál ki adatot.


5. DIRECT RESPONSE COPY ARCHITEKTÚRA


Minden hosszabb értékesítési szövegnek a következő logikai elemekből kell épülnie. Nem szükséges minden elemnek külön szekcióként megjelennie, de a funkciójuknak teljesülnie kell.


5.1. Figyelem és relevancia


Az első mondat vagy címsor nem lehet általános márkaállítás. Azonnal fel kell ismerhetővé tennie a célhelyzetet, a vágyat, a problémát, a különbséget vagy a konkrét ajánlatot.


Gyenge: „Megbízható generálkivitelezés családoknak.”


Erős irány: „Úgy szeretne házat építeni, hogy már a szerződéskor lássa az árat, a határidőt és azt is, pontosan mit kap a pénzéért?”


5.2. Probléma és következmény


A szöveg megmutatja, miért nehéz vagy kockázatos a jelenlegi helyzet, de nem épít mesterséges félelemre. A cél az ügyfél tapasztalatának pontos megfogalmazása.


5.3. Vágyott állapot


Nem terméket, hanem megérkezést, biztonságot, kiszámíthatóságot, kényelmet, időnyereséget, családi élethelyzetet vagy státuszt tesz láthatóvá.


5.4. Egyedi mechanizmus


A szöveg nem állhat meg annál, hogy „minőség”, „megbízhatóság” vagy „szakértelem”. Meg kell neveznie, hogyan jön létre az eredmény. Például:


• fix ár + fix határidő + rögzített műszaki tartalom;
• egy kézben vezetett teljes folyamat;
• több technológia és több mint ezer típusterv közös döntési rendszerben;
• készültségi fokhoz kötött fizetés és dokumentált minőségellenőrzés;
• aktív ár- és ajánlati rekordból működő konfiguráció.


5.5. Bizonyíték


Minden erős állítást bizonyíték követ. Bizonyíték lehet:


• konkrét referencia;
• mérhető cégadat;
• dokumentált folyamat;
• ügyfélvélemény;
• minősítés;
• összehasonlítható műszaki adat;
• fénykép vagy videó;
• ellenőrizhető garanciális vagy szerződéses feltétel.


Bizonyíték nélküli szuperlatívusz nem publikálható.


5.6. Ajánlat


Az ajánlat nem azonos a termékkel. Kötelezően egyértelművé teszi:


• mit kap az érdeklődő;
• milyen készültségben;
• milyen ártól vagy ársávban;
• milyen idővel;
• milyen feltételekkel;
• mi van benne és mi nincs benne;
• milyen következő lépés szükséges;
• mi csökkenti az első döntés kockázatát.


5.7. Kifogáskezelés


A rendszer legalább a CopyBriefben megjelölt elsődleges kifogásokat kezeli. Tipikus témák:


• „Mi van, ha menet közben drágul?”
• „Honnan tudom, hogy valóban ezt a műszaki tartalmat kapom?”
• „Mi történik, ha még nincs telkem?”
• „Mi történik, ha csak 6–12 hónap múlva építkeznék?”
• „Miért bízzak ebben a technológiában?”
• „Miért ne kérjek inkább több külön ajánlatot?”
• „Mennyire módosítható a típusterv?”


A kifogáskezelés nem védekező. Előre tisztáz, bizonyít és egyszerűsíti a döntést.


5.8. Kockázatcsökkentés


A szöveg megmutatja az alacsony kockázatú első lépést: mérnöki konzultáció, kalkuláció, tervajánlás, referencialátogatás, előminősítés vagy lekötési lehetőség.


5.9. CTA


Minden szöveg egy domináns következő lépésre vezet. A CTA konkrét eredményt ígér, nem technikai műveletet nevez meg.


Tiltott: „Tovább”, „Küldés”, „Kattints ide”, „Érdekel”.


Elfogadható: „Kérek részletes kalkulációt”, „Megnézem a hozzám illő házakat”, „Kérek mérnöki konzultációt”, „Időpontot kérek referencialátogatásra”.


6. MAGYAR SZÖVEGMINŐSÉGI SZABVÁNY


A rendszer minden szöveget külön Natural Hungarian ellenőrzésnek vet alá.


Kötelező követelmények:


• természetes magyar mondatszerkezet;
• változatos mondathossz;
• beszélt nyelvi könnyedség, de szakmai pontosság;
• konkrét főnevek és igék;
• kevés felesleges jelző;
• közérthető szakmai magyarázat;
• természetes ritmus és gondolati ív;
• egyértelmű alany és állítás;
• indokolatlan anglicizmusok kerülése;
• modoros, túl ünnepélyes vagy vállalati zsargon kerülése;
• magázás/tegezés következetes alkalmazása a márka szerint.


Automatikusan hibásnak minősülnek az alábbi típusú fordulatok, kivéve ha konkrét bizonyítékkal és egyedi kontextussal indokoltak:


• „álmai otthona”;
• „innovatív megoldások”;
• „minőség kompromisszumok nélkül”;
• „személyre szabott megoldás”;
• „minden igényt kielégítő”;
• „a jövő otthona”;
• „egyedülálló lehetőség”;
• „prémium minőség elérhető áron”;
• „szakértő csapatunk várja”;
• „lépjen velünk kapcsolatba még ma”;
• „legyen részese”;
• „nem csupán…, hanem…” túlhasznált szerkezet;
• indokolatlan gondolatjeles felsorolás;
• üres háromtagú jelzősorok;
• mesterségesen emelkedett, reklámízű mondatok.


7. MÁRKASPECIFIKUS HANG KÖTELEZŐ ÉRVÉNYESÍTÉSE


A közös direct response logika nem jelent közös hangot.


Imperial Holding: magázó, nyugodt, tapasztalt projektigazgatói. Biztonságot, választást és teljes körűséget ad el. Nem harsány, nem olcsó, nem banki és nem túl sötét. A szöveg súlya a kiszámítható döntésen, a vállalati háttéren és az egy kézben vezetett folyamaton van.


Danish Fabrik: tegező, lendületes, meleg és bátorító. Gyorsaságot, fényt, energiahatékonyságot és otthonosságot ad el. Nem lehet hideg műszaki katalógus.


Prefab: magázó, határozott, technológiai és tömör. Pontosságot, bizonyíthatóságot, üzemi gyártást és ellenőrizhetőséget ad el. Nem használhat puha, érzelgős nyelvet.


Bautica: tegező, szakmai, személyes és pontos. Mérnöki kontrollt és felelősséget ad el. A hang emberi, de nem laza.


BauFreund: tegező, barátságos, egyszerű és őszinte. Segít dönteni, nem akar szakmai fölényt demonstrálni.


Casa Moderna: világos, prémium, elegáns és olaszosan életközpontú. Nem sötét luxus, nem státuszfitogtatás és nem általános „prémium” szóhalmozás.


TimberHaus: magázó, nyugodt, természetes és elemző. Faépítési szabadságot, épületfizikai tisztaságot és összehasonlíthatóságot ad el.


A Brand Voice kapu nem kulcsszavakat keres, hanem hangnemet, ritmust, állításmódot, bizonyítéktípust és döntési logikát vizsgál.


8. SZÖVEGTÍPUSONKÉNTI KÖTELEZŐ SZERKEZET


8.1. Főoldal


• célhelyzetet megfogó hero;
• konkrét fő ígéret;
• kanonikus szlogen;
• négy érték rövid bizonyítása;
• választási logika;
• ajánlat vagy ársáv;
• technológiai különbség;
• folyamat;
• bizonyíték;
• kifogáskezelés;
• alacsony kockázatú CTA.


8.2. Típusterv- vagy termékoldal


• kinek és milyen élethelyzetre jó;
• mitől különleges az adott ház;
• bruttó alapterület, szobaszám, ár, önerő, havi törlesztő és idő;
• mi van benne;
• választható technológia és készültségi fok;
• alaprajzi és használati előny;
• módosíthatóság;
• telekalkalmasság;
• finanszírozás;
• minőségbiztosítás;
• saját GYIK;
• konkrét CTA.


8.3. Landing oldal


Egyetlen kampányígéretet visz végig teljes message match mellett. Nem lehet általános vállalati bemutatkozó oldal. A hirdetés hookja, ajánlata, ára, határideje, képe és CTA-ja az első képernyőn visszaköszön.


8.4. Meta hirdetés


• első sorban hook vagy konkrét ajánlat;
• gyorsan érthető termék és előny;
• konkrét ár vagy ajánlati elem;
• egy erős bizonyíték;
• egy kifogás vagy kockázat rövid kezelése;
• egyetlen CTA;
• kanonikus szlogen, ahol kötelező.


8.5. Google Ads


A keresési szándékot tükrözi. Nem márkaverset ír. A fő kulcsszó, konkrét ajánlat, differenciáló előny és CTA jelenik meg. A landing tartalmával teljes egyezés szükséges.


8.6. E-mail


Egy levél egy fő cél. A tárgysor konkrét kíváncsiságot vagy hasznot ígér. A nyitás nem udvariaskodó töltelék. A levél gyorsan eljut az ajánlatig, majd bizonyít és CTA-ra vezet.


8.7. Chatbot és automatizált üzenet


Rövid, emberi és helyzetérzékeny. Nem ismétli mechanikusan a weboldalt. Ismeri az oldalt, házat, konfigurációt, ajánlatot és előző választ. Ismeretlen adatnál nem találgat.


9. COPY GENERÁLÁSI FOLYAMAT


A rendszer a következő elkülönített lépésekben dolgozik:


1. Forrásfeloldás
2. CopyBrief-validáció
3. Ajánlati mag meghatározása
4. Célcsoport és tudatossági szint meghatározása
5. Hook- és big idea változatok
6. Copy vázlat
7. Első szövegváltozat
8. Márkahang-ellenőrzés
9. Direct response kritika
10. Magyar nyelvi szerkesztés
11. Claim- és tényellenőrzés
12. Kifogás- és bizonyítékfedezet ellenőrzése
13. Csatorna- és hosszellenőrzés
14. Emberi jóváhagyás vagy automatikus publikációs kapu


Ugyanaz a modell vagy ügynök nem lehet kizárólagos szerző és végső bíró. A generáló és a kritikai szerep külön prompttal, külön kontextussal és lehetőleg külön modellfutással működik.


10. KÖTELEZŐ SZÖVEGES QA-PONTSZÁMOK


Minden elkészült szöveg 100 pontos értékelést kap az alábbi dimenziókban:


• Brand Voice Fit – 15 pont
• Natural Hungarian – 15 pont
• Direct Response Strength – 15 pont
• Offer Clarity – 10 pont
• Specificity – 10 pont
• Proof Coverage – 10 pont
• Objection Handling – 8 pont
• Message Match – 7 pont
• CTA Strength – 5 pont
• Readability and Rhythm – 5 pont


Publikációs minimum:


• összpontszám legalább 92/100;
• Brand Voice Fit legalább 13/15;
• Natural Hungarian legalább 14/15;
• Direct Response Strength legalább 13/15;
• Claim Coverage 100%;
• kötelező ajánlati adatok 100%;
• tiltott vagy lejárt állítás 0;
• AI-s sablonosság: PASS;
• message match: PASS.


A 92 pont alatti szöveg automatikusan visszakerül javításra. A rendszer nem engedheti meg, hogy egy magas összpontszám elfedjen kritikus hibát. Lejárt ár, hamis claim, rossz megszólítás, hiányzó CTA vagy gyenge ajánlati tisztaság automatikus FAIL.


11. AI-S SZÖVEG DETEKTÁLÁSA


A rendszer külön vizsgálja a generikus mesterséges intelligencia-jegyeket:


• túl sok egyforma hosszúságú mondat;
• sablonos bevezetés;
• azonos szerkezetű háromtagú felsorolások;
• gyakori „nemcsak…, hanem…”;
• indokolatlan metaforák;
• konkrétum nélküli értékállítás;
• ugyanazon szó ismétlése;
• túl sok címke és alcím;
• vállalati közhelyek;
• fordításízű szórend;
• túlmagyarázott lezárás;
• indokolatlan em dash vagy kettőspont-használat;
• túl sok „Ön” vagy „mi”;
• az ügyfél helyett a cégre fókuszáló szöveg.


A detektor nem önmagában dönt. Jelzi a gyanús részeket, majd a magyar nyelvi szerkesztő modul újrafogalmazza azokat.


12. JÓ PÉLDA / ROSSZ PÉLDA ADATBÁZIS


A rendszernek márkánként és szövegtípusonként külön mintatárat kell használnia.


Minden rekord tartalmazza:


• szövegrészlet;
• márka;
• csatorna;
• funkció;
• miért jó vagy rossz;
• melyik szabályt bizonyítja;
• teljesítményadat, ha rendelkezésre áll;
• jóváhagyó;
• érvényesség;
• használhatóság: inspiráció, kötelező minta vagy tiltott minta.


A rendszer nem tanulhat pusztán korábbi publikált anyagból, mert a régi anyag lehet gyenge vagy elavult. Csak kifejezetten jóváhagyott minták kerülhetnek a retrieval kontextusba.


13. KAMPÁNYAUTOMATIZÁCIÓ SZÖVEGMOTORJA


A kampányautomatizáció nem közvetlenül hirdetést ír. Először Campaign Offer Pack készül:


• kampánycél;
• célcsoport;
• aktuális piaci vagy szezonális helyzet;
• kiválasztott házak vagy szolgáltatások;
• aktív árak;
• adható kedvezmény vagy ajándék;
• fedezetellenőrzés;
• valós határidő;
• kapacitás;
• fő ígéret;
• egyedi mechanizmus;
• bizonyíték;
• elsődleges kifogás;
• kockázatcsökkentés;
• CTA;
• landing oldal.


Ebből készülnek csatornánként a szövegek. Minden kampányhoz legalább az alábbi copy-variánsok készülnek:


• ár-első;
• idő-első;
• biztonság-első;
• élethelyzet-első;
• bizonyíték-első;
• technológia-első;
• lekötés- vagy finanszírozás-első.


A variánsok nem puszta szócsere-változatok. Eltérő pszichológiai belépési pontot és érvelési sorrendet használnak.


14. TELJESÍTMÉNYALAPÚ TANULÁS


A rendszer nem a kattintási arányból tanul kizárólag. Szövegvariánsonként követi:


• megállított figyelem;
• átkattintás;
• landing oldali olvasási mélység;
• űrlapindítás;
• űrlapbefejezés;
• kvalifikált lead;
• időpont;
• ajánlat;
• szerződés;
• fedezet;
• lemondás vagy rossz minőségű lead oka.


A nyertes szöveg az, amelyik nyereséges, megfelelő minőségű szerződést hoz. A rendszer külön kezeli a figyelemnyertes és az üzletinyertes kreatívot.


15. FEJLESZTÉSI KÖVETELMÉNYEK


Megépítendő komponensek:


1. Canonical Source Resolver
A BrandID, PageID, CampaignID és AssetType alapján összegyűjti a kötelező forrásokat, verziót rögzít és feloldja az elsőbbséget.


2. CopyBrief Validator
Hiányzó vagy ellentmondásos mezőnél megállítja a folyamatot.


3. Offer Engine
A jóváhagyott termék-, ár-, ajánlati és feltételadatból egységes ajánlati magot állít elő.


4. Copy Generation Orchestrator
A szövegalkotási lépéseket külön futásokban vezérli.


5. Brand Voice Evaluator
Márkánként külön rubric és jóváhagyott minták alapján értékel.


6. Direct Response Critic
Vizsgálja a hookot, ajánlatot, egyedi mechanizmust, bizonyítékot, kifogást, kockázatcsökkentést és CTA-t.


7. Hungarian Editorial QA
Nyelvi természetességet, ritmust, közhelyet, túlírtságot és AI-s szerkezeteket ellenőriz.


8. Claim and Fact Validator
Minden számot, árat, határidőt, garanciát és bizonyítékot aktív rekordhoz köt.


9. Message Match Validator
A hirdetés, landing, űrlap, köszönőoldal és utánkövető üzenet ígéretét összeveti.


10. Copy Scorecard
Pontszámot, hibákat, javítási utasítást és publikációs státuszt ad.


11. Approval Workflow
P0 tartalomnál emberi jóváhagyást kér, majd a jóváhagyott változatot verziózva zárolja.


12. Performance Learning Store
A szövegverziót a teljes üzleti eredménnyel köti össze.


16. KÓDSZINTŰ KÖTELEZŐSÉG


A szabályokat nem promptszövegként, hanem részben kódszintű validációként kell végrehajtani.


Példák:


• kötelező mezők sémavalidációja;
• tiltott CTA-k regex-ellenőrzése;
• szlogen pontos egyezése;
• megszólítás konzisztenciája;
• ár és határidő aktív rekordból;
• lejárati idő ellenőrzése;
• kötelező proof ID jelenléte;
• hirdetés és landing OfferVersionID-egyezése;
• publikáció blokkolása kritikus FAIL esetén.


Az AI csak ott dönthet, ahol valódi nyelvi vagy stratégiai értelmezés szükséges. A determinisztikusan ellenőrizhető szabályt hagyományos szoftver ellenőrzi.


17. ELSŐ BEVEZETÉSI PILOT


A rendszer első pilotja az Imperial Holding márkán készül.


Kötelező pilotcsomag:


• főoldali hero és első három szekció;
• egy teljes típusterv-termékoldal;
• egy kampánylanding;
• hét Meta hirdetésszöveg;
• egy Google Ads RSA csomag;
• három e-mailes utánkövető levél;
• chatbot nyitó és kifogáskezelő válaszok;
• automatikus Copy Scorecard;
• emberi jóváhagyási jegyzőkönyv.


A pilot akkor fogadható el, ha:


• minden szöveg legalább 92/100;
• nincs generikus AI-s rész;
• az Imperial hang logó nélkül is felismerhető;
• a konkrét ajánlat és bizonyíték az első képernyőn megjelenik;
• a hirdetés és landing teljes message match-et mutat;
• a tulajdonosi jóváhagyás után kialakul a Golden Copy Set.


18. GOLDEN COPY SET


A pilotból létrejön a márkánkénti arany standard mintakészlet.


Tartalma:


• 20 jóváhagyott címsor;
• 10 hero;
• 10 ajánlatbemutatás;
• 10 bizonyítékblokk;
• 10 kifogáskezelő blokk;
• 10 CTA-szekció;
• 10 Meta hirdetés;
• 5 landing oldal;
• 5 e-mail;
• jó és rossz példák kommentált párjai.


A későbbi generálás ezekhez méri a hangot és minőséget. Az arany standard nem másolandó szó szerint, hanem minőségi és szerkezeti referencia.


19. PUBLIKÁCIÓS KAPU


Szöveg csak akkor publikálható, ha egyidejűleg teljesül:


• Source Resolution = PASS
• CopyBrief = COMPLETE
• Brand Voice ≥ 90%
• Natural Hungarian ≥ 93%
• Direct Response ≥ 90%
• Claim Coverage = 100%
• Offer Data = VALID
• Proof Coverage = PASS
• Objection Coverage = PASS
• CTA = PASS
• Message Match = PASS
• Legal/Terms = PASS
• Human Approval = REQUIRED/PASS az adott asset szabálya szerint


Bármely kritikus hiba esetén a státusz BLOCKED. A rendszer nem engedhet „ideiglenesen jó”, „majd később javítjuk” vagy „publikálható figyelmeztetéssel” állapotot.


20. VÉGREHAJTÁSI SORREND


P0


• kanonikus forrásresolver;
• CopyBrief séma;
• márkánkénti Voice Profile;
• tiltott kifejezések és CTA-k;
• Claim/Offer/Price validáció;
• Copy Scorecard;
• fail-closed publikáció.


P1


• Direct Response Critic;
• Hungarian Editorial QA;
• message match ellenőrzés;
• jó/rossz példa adatbázis;
• Imperial pilot és Golden Copy Set.


P2


• teljesítményadat-visszacsatolás;
• automatikus variánsképzés;
• márkánkénti modellfinomítás vagy retrieval profil;
• többnyelvű transzkreációs copy QA.


21. ZÁRÓ SZABÁLY


Az Imperial Intelligence rendszerben nem az a kérdés, hogy egy szöveg „elfogadható-e”. Az a kérdés, hogy:


• megállítja-e a megfelelő ember figyelmét;
• pontosan megfogalmazza-e a helyzetét;
• világossá teszi-e az ajánlatot;
• bizonyítja-e az állításait;
• oldja-e a döntés kockázatát;
• megkülönbözteti-e a márkát;
• természetes, erős magyar nyelven szól-e;
• és elvezeti-e az olvasót a következő üzleti lépéshez.


Ami ezt nem teljesíti, az nem kész tartalom, hanem nyersanyag. Nyersanyag nem kerülhet éles felületre.


NEM MEGKERÜLHETŐ MINŐSÉGI KAPUK — VEZETŐI MEGERŐSÍTÉS (2026-08-01)


A minőségi kapuk minden Imperial Intelligence-márkánál és minden tartalmi, kreatív, fejlesztési vagy publikációs feladatnál kötelezőek. SOHA nem kerülhetők meg, nem rövidíthetők le, és sem sürgősség, sem korábbi jóváhagyás, sem technikai hozzáférés nem helyettesítheti a dokumentált ellenőrzéseket.


Következmény: hiányzó, ellentmondásos vagy sikertelen kapu esetén az anyag állapota kötelezően BLOKKOLT. Nem publikálható, nem aktiválható, és nem nevezhető késznek. A készítő nem ellenőrizheti saját munkáját független bírálóként, PASS eredményt pedig csak ténylegesen elvégzett, visszakövethető ellenőrzés után szabad rögzíteni.
