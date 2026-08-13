const SERVICE_PAGES = {
  "/mi-intezzuk/tervezes": {
    id: "EH-HU-501",
    layout: "daily-rhythm",
    eyebrow: "Tervezés a család életére",
    title: "Ne egy rajzot tervezzünk. A hétköznapjaitokat.",
    intro: "A jó alaprajz nem a négyzetméterek elosztásával kezdődik, hanem azzal, hogyan telik egy átlagos reggeletek, hol gyűlik össze a család, mi okoz most bosszúságot, és minek kell öt vagy tíz év múlva is működnie. Ezekből lesz világos térprogram, telekre illesztett terv és vállalható költség.",
    photo: "everyday-service-planning-hero-v1.png",
    primary: ["Elmondom, hogyan szeretnénk élni", "/kezdjuk-egyutt"],
    secondary: ["Megnézem a tervezés menetét", "#tervezesi-ut"],
    signature: "Életből alaprajz",
    opening: {
      question: "Hol landol az iskolatáska? Ki kel fel előbb? Kell-e csendes munkahely? Hogyan használjátok a kertet egy esős novemberi napon?",
      title: "A ház akkor lesz egyszerű, ha a döntések mögött valós élethelyzet áll.",
      copy: "Nem helyiségneveket kérünk egymás után, hanem végigjárjuk a napotokat. A bejárattól a reggeli készülődésen át az esti elcsendesedésig megkeressük azokat a pontokat, ahol egy jó tér időt, rendet és nyugalmat adhat. Így nem egy látványos, de nehezen használható alaprajz készül, hanem olyan otthon, amelynek minden négyzetmétere feladatot kap."
    },
    stages: [
      ["A hétköznapok leltára", "Egy átlagos munkanapot és egy hétvégi napot bontunk fel mozdulatokra: érkezés, tárolás, főzés, tanulás, pihenés, vendégfogadás és kerti élet.", "Ti megmutatjátok, hol ütközik most a család élete; mi ebből használati követelményeket írunk.", "Rangsorolt igénylista készül kötelező, kívánatos és későbbre halasztható elemekkel.", "Ha minden kívánság egyformán fontosnak marad, a ház indokolatlanul nagy és drága lesz."],
      ["A megfelelő méret megtalálása", "Nem a lehető legnagyobb házat keressük, hanem azt a méretet, ahol kényelmesen elfértek, mégsem fizettek évtizedekig kihasználatlan közlekedőkért.", "Ti megadjátok a hosszú távon vállalható keretet és a valóban szükséges helyiségeket; mi területi változatokat készítünk.", "Helyiséglista, becsült nettó alapterület és a méretet növelő döntések külön kimutatása lesz az eredmény.", "A katalógusból kiválasztott méretet nem tekintjük kész válasznak a bútorozás ellenőrzése nélkül."],
      ["Típusterv vagy saját terv", "A típusterv akkor ad valódi ár- és időelőnyt, ha változtatás nélkül vagy csak a megengedett keretben illik hozzátok és a telekhez.", "Ti eldöntitek, mely szokásokból nem engedtek; mi megmutatjuk, hogy ezt kész terv, ésszerű módosítás vagy egyedi tervezés szolgálja jobban.", "Három út költség-, idő- és kockázati különbsége kerül egymás mellé, nem csak három alaprajz.", "A típusterv teljes átrajzolása rendszerint elveszi azt az előnyt, amiért érdemes volt típustervből indulni."],
      ["A telekhez fordított ház", "A tájolás, az utca, a kert, a szomszédok és a terep együtt mondják meg, hová kerülhet a bejárat, a terasz és a legfontosabb ablak.", "Ti elmondjátok, milyen kertkapcsolatot szeretnétek; mi ellenőrizzük a beépíthetőséget, a megközelítést és a benapozást.", "Vázlatos telepítés készül a használati zónákkal, autóhelyekkel és a későbbi bővítés lehetséges helyével.", "A katalógusképen szép homlokzat rossz tájolással sötét nappalit vagy túlmelegedő hálót eredményezhet."],
      ["Bútorokkal ellenőrzött alaprajz", "Az üres falak között minden tágasnak látszik. A valódi próba az, amikor felkerül az ágy, az étkezőasztal, a kanapé, a gardrób és az ajtók nyitási íve.", "Ti megadjátok a megtartandó bútorokat és a napi használatot; mi mérethelyesen berendezzük a fontos helyiségeket.", "Bútorozott alaprajz és közlekedési ellenőrzés mutatja meg, marad-e elegendő hely a használathoz.", "A négyzetméter önmagában nem garantál jó szobát: az arány, az ajtó és az ablak helye ugyanúgy dönt."],
      ["Fény, árnyék és nyári hőérzet", "A sok üveg kellemes lehet télen, de megfelelő külső árnyékolás nélkül nyáron terhet rak a hűtésre és a család komfortjára.", "Ti megfogalmazzátok, hol fontos a reggeli vagy délutáni fény; mi összehangoljuk a tájolást, üvegfelületet és árnyékolást.", "A terven külön jelöljük a benapozási célokat, a túlmelegedés kockázatát és az árnyékolás helyét.", "Az árnyékolást nem hagyjuk a homlokzat elkészülte utáni rögtönzésre, mert akkor drágább és kevésbé szép lehet."],
      ["Gépészet helyet kér", "A gépészeti helyiség, vezetékutak, kültéri egységek és karbantartási hozzáférések nem maradhatnak a terv utolsó sarkába szorítva.", "Ti elmondjátok, milyen komfortot és kezelhetőséget vártok; a szakági tervezők összehangolják a rendszert az építészeti térrel.", "Kijelölt gépészeti zónák, átvezetések és hozzáférési helyek kerülnek a tervbe még a szerkezet lezárása előtt.", "A későn kiválasztott berendezés elvehet a tárolóból, zajt okozhat, vagy bontást kényszeríthet ki."],
      ["A döntések naptára", "Nem kell mindent az első találkozón eldönteni, de minden választásnak van utolsó biztonságos időpontja.", "Ti a döntési pontoknál jóváhagyjátok a változatot; mi előre jelezzük, milyen információ kell hozzá és mire hat a késés.", "Névvel, határidővel és következménnyel ellátott döntési lista kíséri a tervezést.", "A határidő után kért változtatás csak dokumentált költség- és időhatással kerülhet tovább."],
      ["Szakági egyeztetés", "A statika, energetika, gépészet és villamosság nem külön világ: ugyanazon falakban, födémekben és helyiségekben találkoznak.", "Ti a használati igényt hagyjátok jóvá; mi a szakági terveket ütközésmentes, kivitelezhető egésszé rendezzük.", "Egyeztetett tervcsomag készül, amelyben az áttörések, szerkezeti elemek és berendezések helye összeillik.", "A tervlapok közötti ellentmondást nem szabad a kivitelezőre hagyni a helyszínen."],
      ["A terv lezárása", "A lezárt terv nem azt jelenti, hogy soha többé nincs kérdés, hanem azt, hogy a kivitelezéshez szükséges döntések ellenőrzötten és visszakereshetően rendelkezésre állnak.", "Ti végleges jóváhagyást adtok; mi összefoglaljuk a vállalt tartalmat, a nyitott beszerzési választásokat és az eltérések kezelését.", "Jóváhagyott dokumentumjegyzék és egyértelmű tervállapot kerül a szerződéses mellékletek közé.", "Nem indulhat gyártás vagy kivitelezés olyan tervből, amelyen még egymásnak ellentmondó változatok szerepelnek."]
    ],
    proofTitle: "Mit vigyetek haza a tervezés végén?",
    proofItems: [
      ["Használati térkép", "Nemcsak szobák, hanem napi útvonalak, tárolási pontok és egymást zavaró tevékenységek látszanak rajta."],
      ["Bútorozott alaprajz", "Mérethelyes berendezés igazolja, hogy az ajtók, közlekedők és tárolók a valóságban is működnek."],
      ["Telepítési döntés", "A ház helye, tájolása, kertkapcsolata és megközelítése ugyanazon ábrán érthető."],
      ["Döntési napló", "A jóváhagyott változat, a még nyitott választás és annak utolsó időpontja visszakereshető."],
      ["Egyeztetett tervcsomag", "Az építészeti, szerkezeti és szakági tartalom nem egymás mellett, hanem egymással összhangban áll."],
      ["Keretellenőrzés", "A terv mérete és fontos műszaki döntései még a kivitelezési ajánlat előtt visszakapcsolódnak a pénzügyi határokhoz."]
    ],
    faq: [
      ["Mivel kezdődik az első tervezési beszélgetés?", "Nem stílussal vagy tetőformával, hanem a család jelenlegi életével. Megnézzük, kik költöznek, milyen helyzetek ismétlődnek naponta, mi okoz most kényelmetlenséget, és mely változásokra kell az otthonnak később reagálnia."],
      ["Mikor érdemes típustervből indulni?", "Akkor, ha a helyiségkapcsolatok, a méret és a szerkezeti rend alapvetően megfelel, a terv pedig a telken szabályosan és jó tájolással elhelyezhető. Változtatás nélküli típustervnél érvényesül legerősebben az előkészítés ár- és időelőnye."],
      ["Mennyit lehet módosítani egy típusterven?", "Ezt mindig az adott terv szerkezete és az aktív tervezési csomag határozza meg. Egy válaszfal kisebb igazítása és a külső falak, nyílások, tető vagy gépészeti mag áttervezése nem azonos léptékű feladat."],
      ["Mikor jobb az egyedi tervezés?", "Szokatlan telek, összetett családi együttélés, különleges akadálymentességi igény vagy olyan térprogram esetén, amelyet a meglévő tervek csak erőltetett átalakítással tudnának. Ilyenkor a tiszta indulás olcsóbb lehet a sok módosításnál."],
      ["Hogyan derül ki, mekkora házra van szükségünk?", "Helyiséglista helyett használati helyzeteket és bútorozást vizsgálunk. A szükséges alapterületet az ágyak, tárolók, közlekedők és közös terek valós mérete adja, majd külön megjelöljük a kényelmi tartalékot."],
      ["Miért számít ennyit a tárolás?", "Mert a rendet nem a család fegyelme, hanem a tárgyakhoz közel elhelyezett, megfelelő méretű tárolók segítik. A kabát, cipő, porszívó, mosnivaló, játék és kerti eszköz mind saját útvonalat kér."],
      ["Lehet későbbi bővítést előkészíteni?", "Igen, ha már az első ütemben kijelöljük a bővítés helyét, a közlekedési kapcsolatot, a tetőcsatlakozást és a közművek tartalékát. Az előkészítés nem jelent automatikus engedélyt vagy rögzített későbbi árat."],
      ["A garázs is része a tervezési keretnek?", "Ha a projekt része, együtt kell vizsgálni a házzal, a beállással és a kerttel. A különálló vagy csatlakozó garázs másképp hat a beépíthetőségre, a költségre és a napi közlekedésre."],
      ["Hogyan ellenőrzitek a benapozást?", "A telek tájolása, a környező épületek, az évszakok és a nyílások helye alapján. Nemcsak a fény mennyiségét, hanem a nyári túlmelegedés és a szükséges külső árnyékolás kérdését is együtt kezeljük."],
      ["Miért kell már terv közben a költségekkel foglalkozni?", "Mert a négyzetméter, a fesztáv, a tetőforma, a nyílások és a gépészet mind pénzügyi döntés. Ha a keret csak a kész terv után jelenik meg, a visszabontás időt és tervezési díjat emészt fel."],
      ["Mit jelent a bútorozási próba?", "A helyiségeket mérethelyes bútorokkal és használati sávokkal rendezzük be. Így kiderül, nyitható-e az ajtó, elfér-e az étkező körül a szék, használható-e a gardrób, és marad-e nyugodt útvonal a szobák között."],
      ["Mikor vonódik be statikus tervező?", "A szerkezeti rendszer és a koncepció kialakításakor már szükség lehet rá, a részletes statikai terv pedig a kivitelezés előtt készül el. Nagy nyílásoknál, különleges talajnál vagy bonyolult tömegnél különösen korai egyeztetés indokolt."],
      ["A gépészeti rendszer mikor dől el?", "Az alapelvnek és a helyigénynek már az építészeti koncepcióban meg kell jelennie. A konkrét berendezések, méretezés és vezetékezés a szakági tervezésben zárul le, még a szerkezeti áttörések véglegesítése előtt."],
      ["Mi történik, ha menet közben meggondoljuk magunkat?", "A változtatási igényt megvizsgáljuk, majd megmutatjuk a tervezési, engedélyezési, gyártási, költség- és időhatását. Csak tudatos jóváhagyás után módosul a lezárt változat."],
      ["A tervezési díj benne van a típusterv árában?", "A kanonikus szabály szerint a változtatás nélküli típusterv tervezése az alapértelmezett típusház-ajánlat része lehet. A pontos tartalmat, kizárásokat és határidőt mindig az adott, aktív csomag dokumentuma rögzíti."],
      ["Mit nem tartalmaz automatikusan a tervezési szolgáltatás?", "Csak a tételes csomagleírás alapján lehet biztos választ adni. Geodézia, talajvizsgálat, közműszolgáltatói feladat, különleges szakértői vizsgálat vagy egyedi belsőépítészet külön megbízás lehet."],
      ["Kapunk látványtervet is?", "A látványterv körét az adott csomag határozza meg. Fontos, hogy a kép ne helyettesítse a méretezett alaprajzot, metszetet és műszaki tartalmat; a látvány és a megépíthető terv összhangját ellenőrizni kell."],
      ["Miért kell döntési határidő?", "Mert az ablak, gépészet, burkolat vagy elektromos kiállás más-más munkaszakaszt indít el. A késői választás beszerzést állíthat meg vagy már elkészült szerkezet módosítását teheti szükségessé."],
      ["Hogyan készül akadálymentesebben használható otthon?", "Nem egyetlen szélesebb ajtóval. A bejutást, közlekedést, fürdőt, küszöböket, kapcsolókat, tárolást és későbbi segítség lehetőségét összefüggő használati útvonalként tervezzük."],
      ["Kell-e külön dolgozószoba?", "A munkavégzés gyakorisága, a zaj, az ügyfélfogadás, a tárolás és a család napirendje dönti el. Sokszor egy leválasztható fülke elég, máskor valódi, ajtóval zárható helyiség szükséges."],
      ["Hogyan tervezzünk két generációnak?", "A közös és külön élet határait kell tisztázni: bejárat, konyha, fürdő, zaj, gondozás és későbbi használat. Nemcsak két lakrészt, hanem a kapcsolódás szabályait is alaprajzba fordítjuk."],
      ["Mikor tekinthető lezártnak a terv?", "Amikor a jóváhagyott dokumentumjegyzék szerint minden kivitelezéshez szükséges döntés, szakági kapcsolat és tervváltozat egyértelmű, a nyitott termékválasztások pedig határidővel szerepelnek."],
      ["A terv garantálja a hatósági elfogadást?", "Hatósági döntést nem lehet előre garantálni. A tervező a hatályos és helyi előírások alapján készíti el az anyagot, kezeli az egyeztetéseket, és jelzi, ha külön állásfoglalás vagy dokumentum szükséges."],
      ["Mit vigyünk az első találkozóra?", "Ha van telek, helyszínrajzot és elérhető szabályozási adatot; ha van inspiráció, néhány valóban fontos példát; továbbá hozzávetőleges keretet, költözési célt és a család kötelező helyiségigényeit."],
      ["Mi a tervezés legfontosabb eredménye?", "Nem a sok tervlap, hanem az, hogy ugyanazt értitek a ház alatt ti, a tervezők és a kivitelezők. A tér, a műszaki tartalom, a döntések és a pénzügyi határok egymással összhangba kerülnek."]
    ],
    closingTitle: "Mondjátok el, hogyan éltek. Mi ebből építhető otthont tervezünk.",
    closingCta: ["Elkezdem az igénybeszélgetést", "/kezdjuk-egyutt"]
  },

  "/mi-intezzuk/general-kivitelezes": {
    id: "EH-HU-502",
    layout: "responsibility-grid",
    eyebrow: "Generálkivitelezés érthető felelősségekkel",
    title: "Egy építkezés. Egy követhető felelősségi rend.",
    intro: "A generálkivitelezés nem azt jelenti, hogy nektek soha nincs döntésetek. Azt jelenti, hogy minden munkaszakasznak van gazdája, minden átadásnak feltétele, minden változtatásnak látható következménye, és pontosan tudjátok, mikor kinek kell lépnie.",
    photo: "everyday-service-general-hero-v1.png",
    primary: ["Megnézem, mit vállal a generálkivitelező", "#felelossegi-rend"],
    secondary: ["Áttekintem a teljes ütemet", "/szamolok/utemterv"],
    signature: "Felelősségből kész ház",
    opening: {
      question: "Ki veszi át az alapot? Ki jelzi az eltérést? Ki egyezteti a gépészt a szerkezetépítővel? Mikor kell nektek dönteni?",
      title: "A szervezettség ott látszik, ahol két munkaszakasz találkozik.",
      copy: "Egy ház minőségét nem tizenöt különálló szakember jó szándéka tartja össze. Közös terv, világos munkasorrend, dokumentált ellenőrzés és kijelölt felelős kell. A folyamatot ezért nem szakmanevek listájaként mutatjuk meg, hanem átadási pontok soraként: ami nincs rendben, arra nem épül rá a következő munka."
    },
    stages: [
      ["Szerződésből munkaterv", "A vállalt műszaki tartalmat munkaszakaszokra, beszerzésekre, ellenőrzésekre és ügyféldöntésekre bontjuk.", "Ti jóváhagyjátok a szerződéses mellékleteket; a projektvezető ezekből készít végrehajtható sorrendet.", "Közös alapütem, felelősmátrix és dokumentumjegyzék indul el ugyanabból a változatból.", "A homályos tartalom nem válik pontosabbá attól, hogy elkezdődik a munka."],
      ["A munkaterület átvétele", "A telek megközelítését, közműhelyzetét, kitűzését, tárolási lehetőségét és biztonságos használatát még a felvonulás előtt rendezzük.", "Ti biztosítjátok a szerződés szerint szükséges hozzáférést és iratokat; mi megszervezzük a munkaterület működését.", "Átadás-átvételi állapot, fotók, felelősök és a kezdés feltételei kerülnek jegyzőkönyvbe.", "A rendezetlen telek már az első héten időveszteséget és többletmozgatást okozhat."],
      ["Szakágak egymás után, nem egymáson", "A szerkezet, tető, gépészet, villamosság, vakolat és burkolat csak meghatározott előfeltételekkel kezdhető.", "Ti a döntési naptár szerint választotok; mi ellenőrizzük, hogy az előző munkaszakasz átadható-e.", "Minden indulásnak van fogadási feltétele, minden lezárásnak ellenőrzőlistája és bizonyítéka.", "A következő szakág nem takarhatja el az előző kijavítatlan hibáját."],
      ["Beszerzés a megfelelő pillanatban", "A hosszú szállítási idejű termékeket korán, a méretfüggő elemeket csak ellenőrzött helyszíni adat után rendeljük.", "Ti időben jóváhagyjátok a látható termékeket; mi kezeljük a műszaki megfelelést, mennyiséget és érkezést.", "Beszerzési naptár jelzi a döntés, rendelés, szállítás, tárolás és beépítés kapcsolatát.", "A túl korai rendelés módosítási kockázatot, a túl késői választás állásidőt okozhat."],
      ["Minőség az eltakarás előtt", "A vasalást, rögzítést, szigetelést, vezetékeket és tömítéseket akkor kell ellenőrizni, amikor még láthatók és javíthatók.", "Ti megkapjátok az ellenőrzés eredményét; a műszaki felelős csak megfelelő állapotnál engedi a lezárást.", "Fényképes nyilvántartás, mérési eredmény és eltérési lista marad a falak mögötti munkáról.", "A kész festés mögött már sokszoros költség egy apró csatlakozási hiba javítása."],
      ["Változtatás csak következménnyel együtt", "Egy másik burkolat, ablak vagy gépészeti megoldás az áron túl méretet, szállítást és munkasorrendet is módosíthat.", "Ti a teljes hatás ismeretében döntötök; mi nem engedünk szóbeli, visszakereshetetlen változatot a helyszínre.", "Módosítási lap rögzíti a tartalmat, árat, határidőt, kapcsolódó tervet és jóváhagyást.", "A munkaterületi rögtönzés később vitát és egymásra nem illő részleteket hagy maga után."],
      ["Heti előretekintés", "Nem csak azt mondjuk el, mi történt, hanem azt is, mi következik, milyen döntés és szállítás szükséges hozzá.", "Ti előre látjátok a közelgő választásokat; a projektvezető összehangolja a csapatokat és a fogadási feltételeket.", "Rövid, érthető állapotjelentés mutatja a kész, folyamatban lévő, akadályozott és következő feladatokat.", "A késés korai jelzése kezelhető; az utólagos magyarázat már nem adja vissza az elveszett hetet."],
      ["Műszaki átadás szakaszonként", "Az alap, szerkezet, időjárástól zárt állapot, gépészeti alapvezeték és felületkész állapot külön ellenőrzési pont.", "Ti megismeritek a készültséget; a felelős szakemberek dokumentálják a megfelelést és a javításokat.", "A projekt nem egyetlen végső szemlére bízza a minőséget, hanem egymásra épülő átvételekre.", "Ha minden ellenőrzés az utolsó hétre marad, a javítások egymást és a költözést akadályozzák."],
      ["Próbaüzem és használati átadás", "A gépészeti rendszert nem elég felszerelni: be kell állítani, próbálni és a használatát átadni.", "Ti kérdeztek és átveszitek a kezelési tudnivalókat; mi összegyűjtjük a beállításokat, jegyzőkönyveket és dokumentumokat.", "Működési próba, kezelési ismertető és átadási csomag előzi meg a lezárást.", "A bekapcsolt berendezés még nem bizonyítja, hogy a teljes rendszer beszabályozva és dokumentálva van."],
      ["Átadás után is visszakereshető ház", "A későbbi karbantartás, rögzítés vagy átalakítás egyszerűbb, ha a beépített anyagok és rejtett vezetékek adatai megmaradnak.", "Ti megőrzitek és használjátok az átadott csomagot; mi rendezett formában adjuk át a releváns iratokat.", "Fotók, termékadatok, kezelési útmutatók és garanciális kapcsolatok egy helyen maradnak.", "A dokumentálatlan ház minden későbbi beavatkozásnál új feltárást és felesleges bizonytalanságot okozhat."]
    ],
    proofTitle: "Hat pont, ahol a generálkivitelezés értéke kézzelfogható",
    proofItems: [
      ["Egy tervállapot", "A helyszínen mindenki ugyanabból a jóváhagyott dokumentációból dolgozik."],
      ["Átadási feltételek", "A következő munkaszakasz csak ellenőrzött, fogadásra alkalmas állapotra indul."],
      ["Döntési naptár", "Előre látszik, mikor kell terméket vagy műszaki opciót választanotok."],
      ["Eltéréskezelés", "A hiba, javítás, felelős és lezárás nem szóbeli emlék marad."],
      ["Ár- és időhatás", "A változtatás csak a következmények ismeretében válik megrendeléssé."],
      ["Rendezett átadás", "A kész ház mellé használható dokumentáció és kezelési tudás is kerül."]
    ],
    faq: [
      ["Mit jelent pontosan a generálkivitelezés?", "A szerződésben meghatározott munkák összehangolt megszervezését, a szakágak sorrendjét, ellenőrzését és dokumentált átadását. Nem korlátlan szolgáltatás: a pontos feladatot és kizárásokat a műszaki tartalom rögzíti."],
      ["Valóban csak egy kapcsolattartónk lesz?", "A napi projektkommunikációnak kijelölt felelőse van, miközben egyes műszaki vagy szerződéses kérdésekben más jogosult szakember adhat választ. A lényeg, hogy ne nektek kelljen kitalálni, kitől kérjetek döntést."],
      ["Nekünk milyen feladatunk marad?", "A szerződés szerinti ügyféldöntések, jóváhagyások, szükséges dokumentumok és fizetési kötelezettségek. Ezek időpontját előre jelezzük; nem ígérjük, hogy a család részvétele nélkül minden döntés meghozható."],
      ["Ki egyezteti a különböző szakágakat?", "A projektvezetés a jóváhagyott tervek és ütemezés alapján. Az egyeztetéshez a szakági tervezők és felelős kivitelezők bevonása szükséges, az eredmény pedig dokumentált feladatként kerül tovább."],
      ["Hogyan ellenőrzitek a munkák minőségét?", "Munkaszakaszonként meghatározott ellenőrzési pontokkal, mérhető feltételekkel, fényképekkel és szükség szerint jegyzőkönyvvel. Az eltakarás előtti vizsgálatok különösen fontosak."],
      ["Láthatjuk az építkezés állapotát?", "Igen, a projektkövetés módját az aktív szolgáltatási csomag rögzíti. Az állapotjelentés célja, hogy a készültség, a következő feladat, az ügyféldöntés és az esetleges akadály érthetően látszódjon."],
      ["Mi történik, ha hibát találtok?", "Rögzítjük az eltérést, megjelöljük a felelőst és a javítás határidejét, majd ellenőrizzük a lezárást. A következő munkaszakasz nem fedheti el a még nyitott, lényeges hibát."],
      ["Kérhetünk változtatást kivitelezés közben?", "Kérhettek, de előbb meg kell vizsgálni a műszaki megvalósíthatóságot, a kapcsolódó munkákat, a beszerzést, az árat és a határidőt. Jóváhagyás nélkül nem kerülhet új változat a helyszínre."],
      ["Miért kerülhet többe egy késői módosítás?", "Mert már megrendelt terméket, elkészült tervet vagy beépített szerkezetet érinthet, és más szakágak munkáját is újra kell szervezni. Ugyanaz a döntés korábban gyakran egyszerűbb."],
      ["Ki rendeli meg az anyagokat?", "A szerződésben vállalt körben a generálkivitelező szervezi a beszerzést. Az ügyfél által választandó látható termékekhez jóváhagyási időpont tartozik; külön beszerzés csak előre egyeztetett felelősséggel célszerű."],
      ["Mi történik, ha késik egy termék?", "Megnézzük, átszervezhető-e a munkasorrend, van-e műszakilag és esztétikailag elfogadható alternatíva, és milyen hatása marad. Termékcsere csak jóváhagyott tartalommal történhet."],
      ["Hogyan kezelitek az időjárást?", "Az időjárásra érzékeny munkákat előre jelöljük, a feltételeket mérjük, és ahol lehet, védelmet vagy más sorrendet szervezünk. A határidőre gyakorolt tényleges hatást dokumentált események alapján lehet értékelni."],
      ["Mit jelent a készültségi fok?", "Egy meghatározott műszaki állapotot, nem pusztán becsült százalékot. A szerződéses, banki és kivitelezési készültségi fogalmak eltérhetnek, ezért a hozzájuk tartozó tartalmat pontosan össze kell hangolni."],
      ["Mikor számlázható egy munkaszakasz?", "A szerződésben rögzített teljesítési és igazolási feltételek teljesülésekor. Automatikus teljesítésigazolás nincs; a megfelelő jogosultságú ember ellenőrzi és hagyja jóvá a folyamatot."],
      ["Ki igazolja a teljesítést?", "A szerződésben és a vonatkozó szabályokban kijelölt, megfelelő jogosultságú személy. Ezt a rendszert nem helyettesíti automatikus szoftveres állapot vagy fényképfeltöltés."],
      ["Mitől lesz tartható az ütemterv?", "Reális sorrendtől, megfelelő erőforrástól, időben lezárt tervektől, döntésektől és beszerzésektől, valamint attól, hogy az akadályokat korán felismerjük. Egy dátum önmagában nem ütemterv."],
      ["Kapunk heti jelentést?", "A kommunikáció gyakoriságát és csatornáját az adott projektcsomag rögzíti. A jó jelentés nem hosszú: megmutatja, mi készült el, mi következik, mihez kell döntés, és van-e eltérés."],
      ["Bemehetünk bármikor az építkezésre?", "A munkaterület biztonsági szabályai miatt a látogatást egyeztetni kell. Kijelölt időpontban és szükséges védőfelszereléssel úgy lehet körbejárni, hogy a munka és a biztonság ne sérüljön."],
      ["Miért fontos az eltakarás előtti fotózás?", "Mert később nem látható a vasalás, vezeték, rögzítés vagy szigetelési csatlakozás. A kép nem helyettesíti a műszaki ellenőrzést, de fontos visszakereshető bizonyíték és karbantartási segítség."],
      ["Hogyan történik a műszaki átadás?", "Előre ismert ellenőrzési kör, dokumentumlista és hibajegyzék alapján. A nyitott tételekhez felelős és határidő tartozik, a lezárás pedig ellenőrzött állapotot jelent."],
      ["Mi a próbaüzem szerepe?", "Megmutatja, hogy a gépészeti és villamos rendszerek nemcsak be vannak szerelve, hanem működnek, beállíthatók és kezelhetők. A szükséges mérési vagy beszabályozási jegyzőkönyvek a rendszer típusától függenek."],
      ["Milyen dokumentumokat kapunk át?", "A szerződés szerinti terveket, jegyzőkönyveket, releváns termékadatokat, kezelési útmutatókat és garanciális információkat. A pontos átadási jegyzék már a projekt elején rögzítendő."],
      ["Mi nincs benne automatikusan a kulcsrakész állapotban?", "A külső munkák, kerítés, térburkolat, kert és egyes közmű- vagy telekspecifikus tételek általában nem következnek a kifejezésből. Mindig a tételes műszaki tartalom és kizáráslista az irányadó."],
      ["Mi történik az átadás után felmerülő hibával?", "A bejelentés bekerül a garanciális folyamatba, ahol megvizsgálják az okot, a felelősséget és a szükséges intézkedést. A vállalható határidőt és jogcímet nem automata, hanem jogosult szakember állapítja meg."],
      ["Mi a generálkivitelezés legnagyobb előnye?", "Az, hogy a részfeladatok között nem nektek kell felelőst keresni és sorrendet szervezni. A ház egyetlen követhető műszaki, időbeli és dokumentációs rendszerben készül, miközben a döntéseitek továbbra is láthatók maradnak."]
    ],
    closingTitle: "Nem több ígéret kell. Jobban szervezett építkezés.",
    closingCta: ["Átbeszélem a felelősségi rendet", "/kezdjuk-egyutt"]
  },

  "/mi-intezzuk/finanszirozas": {
    id: "EH-HU-503",
    layout: "funding-roadmap",
    eyebrow: "Finanszírozási segítség az első számolástól",
    title: "A házválasztás előtt lássátok, milyen keret reális.",
    intro: "Az otthon ára és a család számára biztonságosan finanszírozható teljes projekt nem ugyanaz a szám. Saját forrás, tartalék, telek, járulékos költségek, banki folyósítás és kivitelezési ütem együtt adja meg, mikor és mekkora ház vállalható.",
    photo: "everyday-service-finance-hero-v1.png",
    primary: ["Felmérem a lehetőségeinket", "/kezdjuk-egyutt"],
    secondary: ["Megnézem a teljes építési költségkeretet", "/szamolok/teljes-projektkeret"],
    signature: "Keretből döntés",
    opening: {
      question: "Mennyi saját forrás maradjon tartaléknak? Mikor folyósít a bank? Melyik számlát mikor kell kifizetni? Mi történik, ha a telek többe kerül a vártnál?",
      title: "Nem a legnagyobb felvehető hitelt keressük, hanem a biztonságosan végigvihető projektet.",
      copy: "A pénzügyi tervezés célja nem egy szép havi törlesztő kiemelése. Előbb teljes költségképet készítünk, elválasztjuk a biztos és a még vizsgálandó tételeket, majd összehangoljuk a család forrásait az építés valós fizetési pontjaival. Aktuális hitel- vagy támogatási adat csak dátumozott partnerforrásból kerülhet a döntésbe."
    },
    stages: [
      ["Családi biztonsági határ", "A bevétel mellett a meglévő kiadásokat, élethelyzeti változásokat és megtartandó tartalékot is figyelembe vesszük.", "Ti mondjátok meg, milyen havi mozgástér mellett érzitek magatokat biztonságban; a pénzügyi szakértő ezt nem írhatja felül pusztán magasabb hitelképességgel.", "Megszületik egy saját családi felső határ, amely különbözik a bank által esetleg engedett legnagyobb összegtől.", "A maximális hitelösszeg választása tartalék nélkül sérülékennyé teheti a teljes építkezést."],
      ["A saját forrás valódi térképe", "Nem minden megtakarítás költhető el az első munkaszakaszban; foglaló, tervezés, közmű és átmeneti lakhatás is kérhet pénzt.", "Ti feltárjátok a rendelkezésre állás időpontját és a nem felhasználható vésztartalékot; mi időrendi ütemezésbe rendezzük a feladatokat.", "Forrástábla különíti el a telket, az építést, a járulékos tételeket és a biztonsági tartalékot.", "A bankszámlán látható teljes összeg nem azonos a kockázat nélkül elkölthető önerővel."],
      ["Teljes építkezés, nem csak házár", "A telek, alapozási eltérés, közmű, külső munka, díjak, költözés és átmeneti költségek a ház csomagárán kívül is megjelenhetnek.", "Ti megadjátok az építkezés határait; mi tételesen szétválasztjuk a vállalt, becsült, telekfüggő és külön megrendelhető részeket.", "Alsó, várható és tartalékkal növelt pénzügyi keret készül, a bizonytalanságok megnevezésével.", "A legkedvezőbb házár félrevezető, ha a befejezéshez szükséges külső tételek kimaradnak mellőle."],
      ["Előminősítés a házválasztás előtt", "A jövedelem, meglévő kötelezettség, életkor, ingatlanfedezet és banki szabály együtt hat a lehetőségekre.", "Ti a szükséges adatokat a jogosult pénzügyi partnernek adjátok meg; mi a házválasztást csak ellenőrzött kerethez igazítjuk.", "Dátumozott előzetes helyzetkép születik, feltételekkel és a még hiányzó dokumentumokkal.", "Az előminősítés nem hitelígéret, és az időközben változó adatok miatt később újra ellenőrizendő."],
      ["Támogatások csak hatályos feltételekkel", "A programok összege, célja, jogosultsága és határideje változhat, ezért emlékezetből vagy régi hirdetésből nem számolunk.", "Ti családi adatot adtok a partnernek; ő elsődleges, dátumozott forrás alapján vizsgálja a lehetőséget.", "A számításban külön soron jelenik meg az ellenőrzött támogatás és minden hozzá tartozó feltétel.", "Feltételezett támogatásra nem építünk visszafordíthatatlan házválasztást vagy szerződéses vállalást."],
      ["A banki folyósítás és az építkezés összehangolása", "A készültségi fok, értékbecslés, számla, önerő felhasználása és folyósítás sorrendje nem válhat el a munkaszakaszoktól.", "Ti elfogadjátok a finanszírozási feltételeket; a kivitelező és a pénzügyi partner egyezteti, mikor milyen igazolás kell.", "Pénzügyi és kivitelezési ütemezés mutatja, mely teljesítés után milyen forrás válhat elérhetővé.", "Ha a kivitelező fizetési pontja megelőzi a banki folyósítást, átmeneti forráshiány állíthatja meg a munkát."],
      ["Dokumentumok előre, nem az utolsó napon", "Jövedelemigazolás, költségvetés, terv, engedélyezési irat, szerződés és értékbecslés egymásra épülhet.", "Ti összegyűjtitek a személyes és tulajdoni dokumentumokat; a partner ellenőrzi az aktuális banki listát.", "Felelősökkel és érvényességi időkkel ellátott dokumentumjegyzék csökkenti az ismételt beszerzést.", "A lejárt vagy eltérő adatot tartalmazó irat késleltetheti az egész döntési sort."],
      ["Tartalék a nem tervezhetőre", "Még alapos előkészítés mellett is lehet telekfeltárásból, hatósági előírásból vagy piaci változásból származó eltérés.", "Ti meghatározzátok, mekkora összeghez nem nyúltok a normál munkák során; mi nem számítjuk be ezt kényelmi bővítésbe.", "A projekttervben külön látszik a működési, műszaki és családi vésztartalék szerepe.", "A nulla tartalék minden apró eltérést azonnal új hitel- vagy műszaki kompromisszummá változtat."],
      ["Döntés több forgatókönyvből", "Ugyanaz a család kisebb házzal nagyobb biztonságot, más készültséggel eltérő időzítést, későbbi bővítéssel alacsonyabb induló terhet választhat.", "Ti rangsoroljátok a teret, időt és havi terhet; mi azonos alapokon mutatjuk meg a változatokat.", "Három pénzügyi út kerül egymás mellé világos előnnyel, lemondással és kockázattal.", "Nem nevezünk optimálisnak olyan változatot, amely csak egyetlen kedvező feltételezéssel működik."],
      ["Újraellenőrzés a szerződés előtt", "A jövedelem, kamatkörnyezet, termékfeltétel, építési ár vagy családi helyzet változhat az első beszélgetés óta.", "Ti friss adatot adtok; a pénzügyi partner újra validálja a lehetőséget, a projekt pedig egyezteti az aktuális ütemet.", "A végleges döntéshez friss, dátumozott forrás- és feltétellista készül.", "Korábbi tájékoztatásból nem keletkezik automatikus hitel-, ár- vagy támogatási jogosultság."],
    ],
    proofTitle: "A pénzügyi döntés hat külön lapja",
    proofItems: [
      ["Családi határ", "Az az összeg és havi teher, amely mellett életetek nem válik folyamatos kockázatkezeléssé."],
      ["Teljes költségkép", "A házon kívüli, telekfüggő, időzített és tartalékolandó tételek is látszanak."],
      ["A források ütemezése", "Nemcsak az összeg, hanem a saját forrás és finanszírozás tényleges elérési ideje is szerepel."],
      ["Feltétellista", "Minden támogatás vagy hitellehetőség mellett ott van a dátum, a forrás és a még vizsgálandó feltétel."],
      ["Folyósítási illesztés", "Az építési teljesítés és a pénz elérkezése ugyanazon munkasorrendben ellenőrizhető."],
      ["Három forgatókönyv", "Nem egyetlen feszes számot, hanem eltérő biztonságú, világosan összehasonlítható utakat kaptok."]
    ],
    faq: [
      ["Mekkora házat engedhetünk meg magunknak?", "Ezt nem lehet pusztán jövedelemből vagy négyzetméterárból megmondani. A teljes projektköltség, a saját forrás időzítése, a vállalható havi teher, a tartalék és a finanszírozási feltételek együtt adnak reális választ."],
      ["Miért nem elég a banki hitelkalkulátor?", "Mert a banki számoló jellemzően a hitel egy részét közelíti, nem a telekkel, járulékos munkákkal és építési folyósítással együtt kezelt teljes projektet. Első tájékozódásra jó, végleges döntésre nem."],
      ["Mennyi önerő szükséges?", "A pontos követelmény banktól, fedezettől, terméktől és ügyfélhelyzettől függ, ezért csak friss partneri vizsgálat után adható meg. A projekt saját biztonsági tartaléka ezen felül is indokolt lehet."],
      ["A telek értéke beszámíthat az önerőbe?", "Bizonyos finanszírozási helyzetekben igen, de a banki értékelés, tulajdoni állapot és termékfeltétel dönt. A vételár, a saját becslés és a bank által elfogadott érték nem feltétlenül azonos."],
      ["Mikor kérjünk előminősítést?", "Még azelőtt, hogy végleges házat választanátok vagy visszafordíthatatlan kötelezettséget vállalnátok. Ha a folyamat elhúzódik vagy az adatok változnak, a szerződés előtt ismételt ellenőrzés szükséges."],
      ["Az előminősítés biztos hitelt jelent?", "Nem. Előzetes helyzetképet ad a megadott adatok és az akkori feltételek alapján. A végső döntéshez teljes dokumentáció, ingatlanértékelés és banki bírálat szükséges."],
      ["Milyen állami támogatások érhetők el?", "Csak az aktuális dátumon hatályos, elsődleges forrásból ellenőrzött programokról adunk partneri tájékoztatást. A jogosultságot családi és ingatlanadatok alapján külön kell vizsgálni; régi kampányanyagból nem számolunk."],
      ["Miért kell biztonsági tartalék?", "Mert telekfeltárás, közmű, hatósági feltétel vagy családi élethelyzet hozhat olyan kiadást, amely nincs a ház alapárában. A tartalék megakadályozhatja, hogy egy kisebb eltérés leállítsa a projektet."],
      ["Mi számít teljes projektköltségnek?", "A telek és kapcsolódó díjak, tervezés, vizsgálatok, engedélyezési feladatok, ház, alapozási eltérések, közművek, külső munkák, finanszírozási költségek, átmeneti lakhatás és költözés is része lehet."],
      ["A típusterv ára mindent tartalmaz?", "Nem. Az ár az alapértelmezett műszaki tartalomhoz, sík telekhez és normál talajviszonyokra számolt alapozáshoz kapcsolódik. Külső munkák, kerítés, térkő, kert és telekspecifikus tételek külön maradhatnak."],
      ["A tervezés benne van a típusház árában?", "Változtatás nélküli típustervnél az alap tervezési tartalom része lehet az ajánlatnak. Minden módosítás, külön szakértői feladat és szolgáltatási határ az aktuális csomagleírás szerint értelmezendő."],
      ["Mi a különbség a nettó ár és a teljes fizetendő összeg között?", "Az építőipari kommunikációban a márka nettó árakat használ, amelyek mellett az alkalmazandó áfa külön szerepel. A családi keretben mindig az adott ügyletre ténylegesen fizetendő összeget kell kezelni."],
      ["Mikor kell kifizetni a kivitelezés árát?", "A szerződésben rögzített munkaszakaszokhoz és igazolt teljesítésekhez igazodva. A pontos fizetési ütemet össze kell hangolni a saját forrással és a bank folyósítási feltételeivel."],
      ["Hogyan folyósít a bank építkezésnél?", "Gyakran készültségi szintek, helyszíni értékelés és dokumentált költségek alapján, de a konkrét rend termékenként eltér. A folyamatot az adott bank friss követelményei szerint kell előre felrajzolni."],
      ["Mi történik, ha a bank később folyósít, mint amikor fizetnünk kell?", "Átmeneti finanszírozási rés keletkezik, amely megállíthatja a következő munkaszakaszt. Ezt a szerződés előtt kell felismerni, majd az ütem, a saját forrás vagy a finanszírozási szerkezet módosításával kezelni."],
      ["Milyen dokumentumokra lehet szükség?", "Személyes és jövedelmi iratokra, tulajdoni dokumentumokra, tervekre, költségvetésre, szerződésre és engedélyezési anyagra is. A pontos, aktuális listát a finanszírozó partner adja meg."],
      ["Meddig érvényes egy előzetes számítás?", "Addig használható biztonsággal, amíg a források, termékfeltételek és személyes adatok nem változnak, de nincs általános örök érvényessége. Minden döntési kapunál dátummal újra kell ellenőrizni."],
      ["Számolhatunk jövőbeni fizetésemeléssel?", "Forgatókönyvként megjelenhet, de a biztonságos alapváltozatot igazolható jelenlegi adatokra érdemes építeni. A még meg nem valósult bevétel ne legyen az egyetlen feltétele a projekt működésének."],
      ["Mi történik, ha változik a kamat?", "A várható havi teher és a teljes visszafizetés változhat, a termék jellegétől függően. A döntés előtt friss partneri ajánlatot és megfelelő érzékenységi számítást kell kérni."],
      ["Érdemes a maximális hitelösszeget felvenni?", "Nem feltétlenül. A bank által engedett felső érték nem ismeri teljesen a család jövőbeli terveit, komfortigényét és kockázattűrését. Saját, alacsonyabb biztonsági határ tudatos döntés lehet."],
      ["Hogyan hasonlítsunk össze két finanszírozási ajánlatot?", "Azonos hitelösszeg, futamidő és feltételek mellett nézzétek a teljes költséget, kamatkockázatot, díjakat, előtörlesztést, biztosítási elvárást és az építési folyósítás rendjét. Egyetlen havi szám nem elég."],
      ["Miért kell több pénzügyi forgatókönyv?", "Mert a kisebb ház, más készültségi szint vagy későbbi bővítés másként osztja el a terhet és a kockázatot. A család így nem egyetlen feszes tervhez kötődik."],
      ["Ki adhat személyre szabott hiteltanácsot?", "Az arra jogosult pénzügyi szolgáltató vagy közvetítő a teljes ügyféladat és aktuális termékfeltételek alapján. Az Everyday Homes folyamata a ház és az építési ütem összehangolását segíti, nem helyettesíti a jogosult tanácsadót."],
      ["Automatikusan elfogadható a rendszer által kiszámolt finanszírozás?", "Nem. A kalkuláció tájékozódást szolgálhat, de hitel-, támogatási vagy szerződéses vállalást csak emberi ellenőrzés és a jogosult fél döntése hozhat létre."],
      ["Mi a pénzügyi előkészítés legfontosabb eredménye?", "Az, hogy még a házválasztás előtt látszik: mennyi a teljes vállalható keret, mikor érkeznek a források, milyen tartalék marad, és mely feltételeket kell a szerződés előtt újra igazolni."]
    ],
    closingTitle: "Előbb legyen biztos a keret. Utána válasszatok házat.",
    closingCta: ["Kérek pénzügyi helyzetképet", "/kezdjuk-egyutt"]
  }
};

function serviceAction(item, secondary = false) {
  if (!item) return "";
  const local = item[1].startsWith("#");
  const target = local ? item[1] : href(item[1]);
  return `<a class="button${secondary ? " button--secondary" : ""}" href="${target}"${local ? "" : " data-route"}>${escapeHtml(item[0])}</a>`;
}

function serviceJourney(page) {
  const anchor = page.anchor || (page.layout === "responsibility-grid" ? "felelossegi-rend" : "tervezesi-ut");
  const labels = page.labels || ["Ti", "Eredmény", "Figyelmeztető jel"];
  const journeyTitle = page.journeyTitle || (page.layout === "funding-roadmap" ? "A pénz útja ugyanúgy tervezendő, mint a házé." : page.layout === "responsibility-grid" ? "Tíz átadási pont tartja egyben a teljes építkezést." : "Tíz állomás választja el az első beszélgetést a lezárt tervtől.");
  return `<section id="${escapeHtml(anchor)}" class="service-journey service-journey--${escapeHtml(page.layout)}"><header><p class="decision-kicker">${escapeHtml(page.signature)}</p><h2>${escapeHtml(journeyTitle)}</h2></header><div class="service-journey__items">${page.stages.map((stage, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(stage[0])}</h3><p>${escapeHtml(stage[1])}</p><dl><div><dt>${escapeHtml(labels[0])}</dt><dd>${escapeHtml(stage[2])}</dd></div><div><dt>${escapeHtml(labels[1])}</dt><dd>${escapeHtml(stage[3])}</dd></div><div><dt>${escapeHtml(labels[2])}</dt><dd>${escapeHtml(stage[4])}</dd></div></dl></article>`).join("")}</div></section>`;
}

function serviceFaq(page) {
  return `<section class="service-faq"><header><p class="decision-kicker">${escapeHtml(page.faqKicker || "Amit érdemes még az elején tisztázni")}</p><h2>${escapeHtml(page.faqTitle || "25 kérdés, amelyből jobb döntés születik")}</h2></header><div class="service-faq__items">${page.faq.map(([question, answer], index) => `<details><summary><span>${String(index + 1).padStart(2, "0")}</span>${escapeHtml(question)}</summary><p>${escapeHtml(answer)}</p></details>`).join("")}</div></section>`;
}

function serviceDeepDive(page) {
  if (!page.deepDive) return "";
  return `<section class="service-deep-dive"><header><p class="decision-kicker">${escapeHtml(page.deepDive.kicker || "Részletes ellenőrzőlista")}</p><h2>${escapeHtml(page.deepDive.title)}</h2><p>${escapeHtml(page.deepDive.intro)}</p></header><div>${page.deepDive.items.map(([title, copy], index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(copy)}</p></article>`).join("")}</div></section>`;
}

function serviceExtraCopy(page) {
  if (!page.extraCopy) return "";
  return `<section class="service-extra-copy"><h2>${escapeHtml(page.extraCopy.title)}</h2>${page.extraCopy.paragraphs.map(copy => `<p>${escapeHtml(copy)}</p>`).join("")}</section>`;
}

function renderServicePage(path) {
  const page = SERVICE_PAGES[path];
  if (!page) return false;
  document.title = `${page.eyebrow} | Everyday Homes`;
  document.querySelector("main").innerHTML = `<article class="service-page service-page--${escapeHtml(page.layout)}" data-page-id="${escapeHtml(page.id)}" data-release-state="review-required"><section class="service-hero"><div class="service-hero__photo" style="background-image:url('${BASE}/assets/photos/${escapeHtml(page.photo)}')" role="img" aria-label="${escapeHtml(page.eyebrow)}"></div><div class="service-hero__copy"><p class="service-brandline">Otthon – egyszerűen.</p><p class="eyebrow">${escapeHtml(page.eyebrow)}</p><h1>${escapeHtml(page.title)}</h1><p class="lede">${escapeHtml(page.intro)}</p><div class="actions">${serviceAction(page.primary)}${serviceAction(page.secondary, true)}</div></div></section><section class="service-opening"><p class="service-opening__question">${escapeHtml(page.opening.question)}</p><div><p class="decision-kicker">${escapeHtml(page.signature)}</p><h2>${escapeHtml(page.opening.title)}</h2><p>${escapeHtml(page.opening.copy)}</p></div></section>${serviceJourney(page)}<section class="service-proof"><header><p class="decision-kicker">${escapeHtml(page.proofKicker || "Kézzelfogható eredmény")}</p><h2>${escapeHtml(page.proofTitle)}</h2></header><div>${page.proofItems.map(([title, copy]) => `<article><h3>${escapeHtml(title)}</h3><p>${escapeHtml(copy)}</p></article>`).join("")}</div></section>${serviceDeepDive(page)}${serviceExtraCopy(page)}${serviceFaq(page)}<section class="service-closing"><div><p>Otthon – egyszerűen.</p><h2>${escapeHtml(page.closingTitle)}</h2></div>${serviceAction(page.closingCta)}</section></article>`;
  setCurrent(path);
  bindRoutes();
  return true;
}

function upgradeServicePage() {
  const path = normalizePath();
  if (SERVICE_PAGES[path]) renderServicePage(path);
}

const serviceNavigateBase = navigate;
navigate = function serviceNavigate(path, replace = false) {
  serviceNavigateBase(path, replace);
  upgradeServicePage();
};

window.addEventListener("popstate", upgradeServicePage);
upgradeServicePage();
