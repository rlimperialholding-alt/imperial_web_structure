const BASE = "/site-preview/everyday-homes";

const pages = {
  "/": {
    id: "EH-HU-001", eyebrow: "Everyday Homes", title: "A saját otthon nem lehet örökké csak terv.",
    intro: "Találjátok meg azt a házat, amelyik illik a családotokhoz, a telketekhez és a lehetőségeitekhez. Segítünk átlátni a választást, a finanszírozást és az építkezés teljes útját.",
    image: "young", primary: ["Megnézem a házakat", "/nekunk-valo-hazak"], secondary: ["Megnézem, mi fér bele", "/keretbol-otthon"],
    sections: [
      ["Nem építkezni szeretnétek. Hanem hazamenni.", "Nem kell hónapokon át külön szakembereket keresnetek, részajánlatokat bogarásznotok és minden nap új problémát megoldanotok. Előbb lássátok, milyen ház jöhet szóba, mire elég a keretetek, és mi történik az első döntéstől az átadásig.", ["Házválasztás érthetően", "A teljes keret áttekintése", "Egymásra épülő lépések"]],
      ["Milyen életre tervezzük?", "Nem pusztán alaprajzot választotok. Helyet a közös reggeliknek, a gyerekszobáknak, az otthoni munkának és annak az életnek, amelyet évek múlva is jó lesz itt élni.", ["Első saját otthon", "Növekvő család", "Kisebb, kényelmesebb ház", "Otthon munkához is"]],
      ["Előbb tudjátok meg, mi fér bele.", "A cél nem a lehető legnagyobb ház. Olyan otthon mellett érdemes dönteni, amelyet biztonsággal végig tudtok vinni, és amely mellett a beköltözés után is marad mozgásteretek.", ["Saját forrás", "Teljes projektkeret", "Finanszírozási segítség"]]
    ],
    quote: ["Kell egy otthon mindenkinek.", "Otthon – egyszerűen."]
  },
  "/otthonvalaszto": {
    id: "EH-HU-002", eyebrow: "Otthonválasztó", title: "Találjátok meg a házat, ahová jó lesz hazamenni.",
    intro: "Nem zúdítjuk rátok az összes alaprajzot. Néhány fontos kérdésből indulunk, majd azokat az otthonokat mutatjuk meg, amelyek valóban szóba jöhetnek.",
    image: "mother", primary: ["Elindítom az Otthonválasztót", "/kezdjuk-egyutt"], secondary: ["Inkább előbb számolnék", "/keretbol-otthon"],
    sections: [
      ["Induljunk abból, ami valóban számít", "Hányan költöznétek? Mi nem hiányozhat? Mekkora keret fér bele kényelmesen? Van már telketek? Ezek a válaszok nem kizárnak, hanem rövidebbé és értelmesebbé teszik a választást.", ["Család és jövőbeli változás", "Kötelező helyiségek", "Kényelmesen vállalható keret", "Telek és költözési cél"]],
      ["Ezeket érdemes közelebbről megnéznetek", "A találatok az igényeitek és az ellenőrzött házadatok alapján készülnek. Ha nincs pontos találat, nem erőltetünk rátok rossz választást: megmutatjuk, melyik feltételen érdemes változtatni.", ["Legfeljebb három közeli találat", "Világos különbségek", "Egy kizáró szempont házanként"]],
      ["Egy pillantás, és látszik a lényeg", "A háznév, a bruttó alapterület, a szobák, az ellenőrzött nettó ár + ÁFA és az építési idő egy összefüggő egységben jelenik meg. Üres vagy nem igazolt mezővel ház nem kerülhet a találatok közé.", ["Azonos adatmezők", "Teljes házkép", "Nincs elrejtett műszaki csomag"]]
    ]
  },
  "/nekunk-valo-hazak": {
    id: "EH-HU-002", eyebrow: "Nekünk való házak", title: "Ne száz tervet nézzetek. A hozzátok illőket.",
    intro: "A házakat méret, élethelyzet és telekadottság szerint rendezzük. Minden gyűjtőoldal más döntést segít, és csak ellenőrzött termékadatot mutathat.",
    image: "young", primary: ["Első otthonokat nézek", "/otthonok/30-69"], secondary: ["Családi otthonokat nézek", "/otthonok/70-99"],
    links: [["Induló otthonok 30–69 m²", "/otthonok/30-69"], ["Családi otthonok 70–99 m²", "/otthonok/70-99"], ["Tágasabb otthonok 100–130 m²", "/otthonok/100-130"], ["Keskenyebb telekre", "/otthonok/keskenyebb-telekre"], ["Könnyebben használható otthonok", "/otthonok/konnyebb-hasznalat"], ["Később bővíthető házak", "/otthonok/bovitheto"]],
    sections: [["A katalógus nem találgat", "HousePlanID, kép, alaprajz és alapterület csak azonosított forrásból érkezhet. Ár, technológia és építési idő kizárólag aktív Everyday Homes-rekordból jelenhet meg.", ["Ellenőrzött házadat", "Érthető összehasonlítás", "Házspecifikus előny"]]]
  },
  "/keretbol-otthon": {
    id: "EH-HU-004", eyebrow: "Keretből otthon", title: "Előbb lássátok, mi vállalható. Utána válasszatok házat.",
    intro: "A ház ára csak az egyik sor. A teljes döntéshez együtt kell látni a saját forrást, a finanszírozást, a telekhez kapcsolódó tételeket és a biztonsági tartalékot.",
    image: "senior", primary: ["Összerakom a teljes keretet", "/szamolok/teljes-projektkeret"], secondary: ["Havi teherrel számolok", "/szamolok/havi-teher"],
    sections: [
      ["Ne a legnagyobb elérhető összeget keressétek", "A jó keret nemcsak bankilag lehetséges, hanem a család mindennapjaiban is vállalható. A számolásnak meg kell mutatnia, miből indul ki és mely adat változhat.", ["Saját forrás", "Kényelmes havi vállalás", "Tartalék váratlan tételekre"]],
      ["A teljes projektet számoljuk", "A telek, a tervezés, az alapozás, a közművek, a külső munkák és a költözés nem tűnhet el a ház ára mögött.", ["Ismert tétel", "Becsült tartomány", "Még vizsgálandó költség"]],
      ["Minden számnak legyen dátuma és forrása", "Kamat, támogatás, törlesztő vagy kivitelezési ár csak friss, azonosított adatból jelenhet meg. A számoló eredménye tájékoztató kiindulópont, nem automatikus ajánlat.", ["Forrásverzió", "Érvényesség", "Feltételezések"]]
    ]
  },
  "/igy-lesz-egyszeru": {
    id: "EH-HU-005", eyebrow: "Mi intézzük", title: "Építkezés, ami nem lesz a másodállásotok.",
    intro: "Nem kell háromfelé szaladnotok. A házválasztás, a keret, a tervezés és a kivitelezés egymásra épülő feladat. Mindig lássátok, mi következik és ki felel érte.",
    image: "mother", primary: ["Elmondom, hol tartunk", "/kezdjuk-egyutt"], secondary: ["Megnézem a házakat", "/nekunk-valo-hazak"],
    sections: [
      ["1. Először a házat választjátok ki", "A ház akkor jó, ha elfértek benne, szerethető marad, és a költsége mellett a beköltözés után is marad mozgásteretek.", ["Élethelyzet", "Méret és szobák", "Alaprajz és változtathatóság"]],
      ["2. A keretet mellé tesszük", "Átnézzük a saját forrást, a szükséges finanszírozást és a ház árán túli tételeket. Nem a legnagyobb házat keressük, hanem a végigvihető döntést.", ["Nettó ár + ÁFA", "Teljes költségkép", "Finanszírozási lépések"]],
      ["3. A telket és a házat együtt nézzük", "A telek formája, helyi szabályai, tájolása, közművei, megközelítése és talaja döntheti el, hogy a kiválasztott ház valóban jó választás-e.", ["Beépíthetőség", "Tájolás", "Alapozási kockázat"]],
      ["4. Egyértelművé tesszük, mit kaptok", "A terv, a műszaki tartalom, a vállalási ár, a fizetési ütemezés és a fő határidők egy rendszerben legyenek láthatók.", ["Mi van az árban?", "Mi marad külön?", "Mi változtathatja meg?"]],
      ["5. Az építkezésnek ütemterve van", "A munkaszakaszok, ellenőrzési pontok és ügyféldöntések nem az utolsó pillanatban derülnek ki. Minden változtatás ár- és időhatását előre kell látni.", ["Szakaszok", "Ellenőrzési pontok", "Döntési határidők"]]
    ]
  },
  "/kozelrol": {
    id: "EH-HU-006", eyebrow: "Közelről", title: "Ne csak azt nézzétek meg, mit ígérünk.",
    intro: "Egy elkészült otthon vagy egy futó építkezés többet mutat bármely látványtervnél. A helyszínek csak jóváhagyott referenciarekordból jelenhetnek meg.",
    image: "generations", primary: ["Megnéznék egy házat", "/kezdjuk-egyutt"], secondary: ["Családok történetei", "/kozelrol/csaladok-tortenetei"],
    sections: [["Olyat nézzetek meg, ami nektek releváns", "Méret, technológia és készültségi állapot szerint keressük meg a hasznos helyszínt. Nem díszletet mutatunk, hanem olyan részleteket, amelyek segítik a döntést.", ["Elkészült otthon", "Futó építkezés", "Szakmai kérdések a helyszínen"]]]
  },
  "/elso-lepesek": {
    id: "EH-HU-007", eyebrow: "Kérdésből döntés", title: "Előbb a jó kérdést találjátok meg.",
    intro: "A tudástár nem általános cikklista. Minden útmutató egy konkrét családi döntést tesz érthetőbbé, majd a megfelelő számolóhoz vagy következő lépéshez vezet.",
    image: "young", primary: ["A házmérettel kezdem", "/elso-lepesek/mekkora-haz"], secondary: ["A teljes költséget nézem", "/elso-lepesek/teljes-koltseg"],
    links: [["Mekkora házra van szükségetek?", "/elso-lepesek/mekkora-haz"], ["Hogyan spórol egy jó alaprajz?", "/elso-lepesek/jo-alaprajz"], ["Hét telekellenőrzés foglaló előtt", "/elso-lepesek/telekvasarlas"], ["Milyen költség van a ház árán túl?", "/elso-lepesek/teljes-koltseg"], ["Melyik technológia mikor jó?", "/elso-lepesek/technologia-valasztas"], ["Mitől tartható az ütemterv?", "/elso-lepesek/tarthato-utemterv"]],
    sections: [["A válaszok ellenőrizhetők", "Minden szakmai oldal szerzőt, ellenőrzési dátumot és forráslistát kap. Számszerű példa csak jóváhagyott számításból készülhet.", ["Valós kérdés", "Világos módszer", "Használható következő lépés"]]]
  },
  "/a-fontos-kerdesek": {
    id: "EH-HU-008", eyebrow: "A fontos kérdések", title: "Amit a döntés előtt érdemes tisztázni.",
    intro: "Rövid, egyenes válaszok a telekről, a típustervek módosításáról, az árról, a finanszírozásról és a várható ütemezésről.",
    image: "mother", primary: ["Felteszem a saját kérdésem", "/kezdjuk-egyutt"],
    sections: [
      ["El lehet kezdeni telek nélkül?", "Igen. Több, méretben és költségszintben megfelelő házzal is elindulhattok. A végleges választáshoz azonban ellenőrizni kell a telek beépíthetőségét és adottságait.", ["Előzetes házlista", "Telekellenőrzés", "Végleges illesztés"]],
      ["Módosítható egy típusterv?", "Igen, de nem minden változtatás egyforma. Az egyszerűen választható opciókat külön kell választani az újratervezést és új műszaki-pénzügyi számítást igénylő módosításoktól.", ["Választható opció", "Tervmódosítás", "Egyedi tervezés"]],
      ["Mikor kapunk végleges árat?", "A végleges vállalási árhoz rögzíteni kell a tervet, a telek adottságait, a műszaki tartalmat, a készültségi szintet és a szerződéses feltételeket.", ["Aktuális ár", "Telekfüggő tételek", "Végleges vállalás"]]
    ]
  },
  "/kezdjuk-egyutt": {
    id: "EH-HU-009", eyebrow: "Kezdjük ott, ahol tartotok", title: "Nem kell minden választ tudnotok.",
    intro: "Mondjátok el, mi van már meg: telek, terv, elképzelés vagy pénzügyi keret. Innen egyetlen, értelmes következő lépést jelölünk ki.",
    image: "young", primary: ["Házat választanék", "/otthonvalaszto"], secondary: ["A keretemet mérném fel", "/keretbol-otthon"],
    sections: [["Öt válasz elég az induláshoz", "Hol építkeznétek? Van telketek? Hányan költöznétek? Mekkora házban gondolkodtok? Milyen kerettel számoltok? Ha valamelyik még nyitott, éppen azt tisztázzuk először.", ["Van telkünk", "Még telket keresünk", "Van saját tervünk", "Házat szeretnénk választani"]]],
    notice: "Az űrlap beküldése csak kapcsolatfelvételi kérés. Nem keletkeztet automatikus ajánlatot, szerződést, felelősségelismerést vagy teljesítésigazolást."
  },
  "/kell-egy-otthon-mindenkinek": {
    id: "EH-HU-010", eyebrow: "Küldetésünk", title: "A saját otthon ne maradjon örökké terv.",
    intro: "Azért dolgozunk, hogy a családi ház választása és megépítése átláthatóbb, egyszerűbb és vállalhatóbb legyen.",
    image: "generations", primary: ["Megnézem, mi illik hozzánk", "/otthonvalaszto"],
    sections: [["A család valódi életéből indulunk ki", "Nem mindenkinek kell nagyobb ház. Olyan otthon kell, amelyben jó élni, és amelynek a költségei nem teszik tönkre a család mindennapjait.", ["Érthető választás", "Követhető út", "Használható otthon"]], ["Mit egyszerűsítünk?", "A házválasztás, a tervezés, a finanszírozás és a kivitelezés feladatait rendezzük egymás mellé. Amit még nem lehet igazolni, azt nem ígérjük meg.", ["Kevesebb bizonytalanság", "Világos felelősség", "Ellenőrizhető döntések"]]],
    quote: ["Kell egy otthon mindenkinek.", "Ez nem kampánymondat. Ez a dolgunk."]
  },
  "/garanciak-es-utogondozas": {
    id: "EH-HU-011", eyebrow: "Átadás után", title: "A kulcsátadás után is legyen kitől kérdezni.",
    intro: "Az új otthon első évében lehetnek beállítások, ellenőrzések és kérdések. Közérthetően különválasztjuk a törvényi jótállást, a vállalt többletszolgáltatásokat és a tulajdonosi karbantartást.",
    image: "senior", primary: ["Megnézem a vállalások rendszerét", "/biztonsag/vallalasaink"],
    sections: [["Hibabejelentés, érthetően", "Megmutatjuk, milyen adat és fotó segíti a gyors kivizsgálást, ki válaszol, hogyan követhető az ügy, és mikor van szükség helyszíni ellenőrzésre.", ["Bejelentés", "Visszaigazolás", "Vizsgálat", "Megoldás és lezárás"]], ["A konkrét garanciák adatkapusak", "Időtartam, díjmentes karbantartás vagy műszaki vizsgálat csak jóváhagyott garanciaszabályból jelenhet meg. A staging felület ezért nem állít olyat, amit a végleges dokumentum még nem igazol.", ["Hatályos jogi forrás", "Jóváhagyott többletvállalás", "Verziózott tájékoztató"]]]
  }
};

const lifePages = [
  ["/elso-sajat-otthon","EH-HU-101","Első saját otthon","A saját otthon lehet a következő valós lépés.","Nem kell előre tudnotok minden választ. Először azt nézzük meg, milyen keretből, milyen telekkel és milyen időtávon lehet felelősen elindulni.",["Jelenlegi lakhatási költség és vállalható keret","Önerő és pénzügyi előszűrés","Kiszámítható méretű induló házak","Telek előtt vagy telek után"],"Megnézem, honnan érdemes indulnunk"],
  ["/most-leszunk-csalad","EH-HU-102","Most lesztek család","Legyen helye annak is, ami most kezdődik.","A baba érkezése nemcsak plusz szobát jelent. Számít a háló és a gyerekszoba kapcsolata, a babakocsi helye, a mosás, a pihenés és a kert biztonságos elérése.",["Az első két év használati helyzetei","Tárolás a bejárat közelében","Közeli, mégis nyugodt hálók","Későbbi testvér vagy dolgozószoba"],"Mutassatok családindításhoz való házakat"],
  ["/tobb-hely-a-csaladnak","EH-HU-103","Növekvő család","Ne csak nagyobb legyen. Működjön jobban.","A zsúfoltságot nem mindig több négyzetméter oldja meg. A jobb alaprajz, a külön hálózóna, a valódi tároló és a használható közös tér adhatja vissza a család nyugalmát.",["Három vagy négy háló","Közös tér és csendes zóna","Valódi tárolóhelyek","A régi ingatlan és az új otthon időzítése"],"Megnézem a nagyobb családra tervezett házakat"],
  ["/otthon-es-munka","EH-HU-104","Otthon és munka","Munkaidőben legyen iroda. Utána legyen újra otthon.","Az étkezőasztalnál kialakított állandó munkahely hamar elveszi a közös tér nyugalmát. A munka férjen el úgy, hogy ne uralja a család életét.",["Külön szoba vagy leválasztható sarok","Fény és akusztika","Ügyfélfogadás lehetősége","Későbbi gyerekszobává alakítás"],"Kérek otthoni munkához illő házajánlást"],
  ["/kisebb-haz-konnyebb-elet","EH-HU-105","Könnyebb mindennapok","Pont elég hely. Kevesebb teher.","A kisebb ház nem lemondás, ha a fontos terek kényelmesek, a közlekedők nem viszik el a négyzetmétereket, és az üzemeltetés hosszú távon is vállalható.",["A valóban használt terek","Egyszintes elrendezés","Tárolás és kertkapcsolat","Fenntartási szempontok"],"Megnézem a könnyebben fenntartható házakat"],
  ["/ket-generacio-egy-otthon","EH-HU-106","Két generáció","Közel egymáshoz. Mégis saját térben.","A többgenerációs otthon akkor működik jól, ha a segítség közel van, de a napirend, a pihenés és a vendégfogadás nem zavarja egymást.",["Külön bejárat vagy közös előtér","Két fürdő és intim zónák","Közös vagy részben önálló konyha","Könnyebb, biztonságosabb használat"],"Megnézem a többgenerációs lehetőségeket"],
  ["/kesobb-bovitheto-otthon","EH-HU-107","Bővíthető otthon","Ne fizessetek ma azért, amire csak évek múlva lesz szükség.","Ha a jelenlegi keretből kisebb ház vállalható felelősen, érdemes már most kijelölni a későbbi szoba, dolgozó, garázs vagy fedett terasz helyét.",["Bővítési irány","Telek és beépíthetőség","Szerkezeti és gépészeti előkészítés","Mostani és későbbi alaprajz"],"Kérek bővíthetőségi javaslatot"]
];

lifePages.forEach(([path,id,eyebrow,title,intro,items,cta], index) => {
  pages[path] = { id, eyebrow, title, intro, image: index % 3 === 0 ? "young" : index % 3 === 1 ? "mother" : "generations", primary: [cta, "/kezdjuk-egyutt"], sections: [["Mire figyelünk ennél az élethelyzetnél?", intro, items]] };
});

const houseCollections = [
  ["/otthonok/30-69","EH-HU-201","Induló otthonok 30–69 m²","Az első saját ház nem attól lesz otthon, hogy nagy.","Kompakt házak pároknak, kisebb családoknak és azoknak, akik tudatosan kevesebb fenntartási költséget szeretnének."],
  ["/otthonok/70-99","EH-HU-202","Családi otthonok 70–99 m²","Mindenkinek jusson hely. Felesleges terek nélkül.","Két-három háló, használható nappali és valódi tárolás úgy, hogy a teljes költség ne nőjön ellenőrizetlenül."],
  ["/otthonok/100-130","EH-HU-203","Tágasabb otthonok 100–130 m²","Több szoba, több lehetőség – átgondolt keretek között.","Nagyobb családoknak, külön dolgozószobát vagy vendégteret keresőknek. Minden plusz térnél megmutatjuk, milyen használati értéket ad."],
  ["/otthonok/keskenyebb-telekre","EH-HU-204","Keskenyebb telekre","A telek keskenyebb. A lehetőségek nem feltétlenül.","A telekszélesség, az oldalkert, a tájolás és a bejárat együtt dönti el, melyik terv működhet."],
  ["/otthonok/konnyebb-hasznalat","EH-HU-205","Könnyebben használható otthonok","Otthon, amelyben hosszú távon is könnyebb mozogni.","Egyszintes, kevés szintkülönbséggel, jól járható közlekedőkkel és később is alakítható fürdővel tervezhető házak."],
  ["/otthonok/bovitheto","EH-HU-206","Később bővíthető házak","Most elég. Később tovább nőhet veletek.","Olyan alapmodellek, amelyeknél már a tervezéskor kijelölhető a bővítés lehetséges iránya."]
];
houseCollections.forEach(([path,id,eyebrow,title,intro]) => pages[path] = {id,eyebrow,title,intro,image:"young",primary:["Kérek személyes házajánlást","/kezdjuk-egyutt"],sections:[["Mit láttok majd minden háznál?","A kártya csak akkor jelenhet meg, ha a ház képe, neve, bruttó alapterülete, hálószobaszáma, ellenőrzött nettó ára + ÁFA és építési ideje egyaránt rendelkezésre áll.",["Teljes házkép","Azonosított alaprajz","Ellenőrzött kereskedelmi adat","Egyetlen házspecifikus előny"]]],notice:"A termékkártyák ezen a staging builden adatkapu miatt rejtve maradnak. Ellenőrizetlen árat, határidőt vagy házadatot nem jelenítünk meg."});

const guides = [
  ["/elso-lepesek/mekkora-haz","EH-HU-701","Mekkora házra van valóban szükségetek?","Ne négyzetméterrel kezdjetek. A napjaitokkal.",["Hányan éltek majd itt?","Mely funkciók kötelezők?","Mennyi helyet visz el a közlekedés?","Mit ad hozzá a kert és a terasz?"]],
  ["/elso-lepesek/jo-alaprajz","EH-HU-702","Hogyan spórol egy jó alaprajz?","Kevesebb fal, rövidebb közlekedő, több használható hely.",["Rövid közlekedők","Közeli vizes helyiségek","Egyszerű szerkezeti rend","Beépített tárolás"]],
  ["/elso-lepesek/telekvasarlas","EH-HU-703","Telekvásárlás","A foglaló előtt derüljön ki, mit lehet valóban építeni.",["Övezet és beépíthetőség","Telekszélesség és szintkülönbség","Talaj és közmű","Megközelítés és tájolás"]],
  ["/elso-lepesek/teljes-koltseg","EH-HU-704","A ház árán túl","A ház ára fontos. A teljes projekt ára döntő.",["Telek és tervezés","Vizsgálatok és közművek","Külső munkák","Költözés és tartalék"]],
  ["/elso-lepesek/technologia-valasztas","EH-HU-705","Technológiaválasztás","Előbb a cél. Utána az anyag.",["Tervezési szabadság","Építési folyamat","Komfort és energia","Javíthatóság és bővíthetőség"]],
  ["/elso-lepesek/tarthato-utemterv","EH-HU-707","Tartható ütemterv","Nem a rajtnál kell gyorsnak lenni. A teljes út legyen szervezett.",["Lezárt döntések","Tervkészültség","Beszerzés és kapacitás","Változtatások időhatása"]]
];
guides.forEach(([path,id,eyebrow,title,items]) => pages[path]={id,eyebrow,title,intro:"Rövid, közérthető döntési útmutató ellenőrizhető módszerrel és egyértelmű következő lépéssel.",image:"mother",primary:["Tovább a megfelelő eszközhöz","/kezdjuk-egyutt"],sections:[["Mit nézünk végig?","Nem általános tanácsot adunk. A döntést azokra a tényezőkre bontjuk, amelyek az adott háznál vagy teleknél valóban számítanak.",items]],notice:"A szakmai oldal számszerű példái csak forrással, ellenőrzési dátummal és feltételezésekkel kerülhetnek ki."});

const fallbackGroups = {
  "/szamolok/hazkoltseg": ["EH-HU-301","Mennyibe kerülhet a házunk?","Adjátok meg, mit szeretnétek. Megmutatjuk, miből áll össze a várható költség."],
  "/szamolok/havi-teher": ["EH-HU-302","Mekkora havi teher férhet bele?","Ne azt számoljátok, mennyi hitelt kaphattok. Azt, mi marad kényelmes."],
  "/szamolok/teljes-projektkeret": ["EH-HU-303","Teljes projektkeret","A ház ára csak az egyik sor."],
  "/szamolok/utemterv": ["EH-HU-304","Mikor költözhetünk?","Nem egyetlen dátumot mondunk. Megmutatjuk, mi vezet el odáig."],
  "/szamolok/felujitas-vagy-uj": ["EH-HU-305","Felújítsunk, bővítsünk vagy építsünk újat?","Nem mindig az új ház a jobb döntés. De nem mindig a felújítás az olcsóbb."],
  "/szamolok/energia-es-koltseg": ["EH-HU-306","Építési és fenntartási költség együtt","Amit ma beépítetek, azt évekig fizetitek – vagy élvezitek."],
  "/szamolok/gyors-hazellenorzes": ["EH-HU-307","Melyik ház illik hozzánk?","Hét kérdés. Egy rövidebb, értelmesebb lista."],
  "/mibol-epuljon": ["EH-HU-401","Miből épüljön?","Nem a hangosabb technológia a jobb. Az, amelyik a ti házatokhoz illik."],
  "/biztonsag/vallalasaink": ["EH-HU-601","Mit vállalunk?","Amit vállalunk, annak helye van a szerződésben."],
  "/kozelrol/csaladok-tortenetei": ["EH-HU-606","Családok történetei","Minden ház mögött más döntés volt."]
};
Object.entries(fallbackGroups).forEach(([path,[id,eyebrow,title]]) => pages[path]={id,eyebrow,title,intro:"Az oldal az Everyday Homes kanonikus tartalmi terve alapján készült. Minden változó adat csak azonosított, aktuális forrásból jelenhet meg.",image:"generations",primary:["Kezdjük a saját helyzetünkkel","/kezdjuk-egyutt"],sections:[["Érthető eredmény, látható feltételekkel","A válasz megmutatja, mely adatok biztosak, melyek becslések, és mi az, amit még külön meg kell vizsgálni.",["Forrás és érvényesség","Feltételezések","Bizonytalansági tartomány","Következő döntés"]]],notice:"Ez a funkció tartalmi és vizuális staging. Nem ad automatikus ajánlatot, költözési garanciát vagy finanszírozási ígéretet."});

function normalizePath() {
  let path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path.startsWith(BASE)) path = path.slice(BASE.length) || "/";
  return path;
}

function href(path) { return path === "/" ? `${BASE}/` : `${BASE}${path}`; }
function mediaClass(image) { return image === "generations" ? "hero__media--generations" : image === "mother" ? "hero__media--mother" : image === "senior" ? "hero__media--senior" : ""; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char])); }

function renderPage(page, path) {
  document.title = `${page.eyebrow} | Everyday Homes staging`;
  const main = document.querySelector("main");
  const action = (item, secondary = false) => item ? `<a class="button${secondary ? " button--secondary" : ""}" href="${href(item[1])}" data-route>${escapeHtml(item[0])}</a>` : "";
  const sections = (page.sections || []).map(([title, body, items], sectionIndex) => `
    <section class="section ${sectionIndex % 2 === 0 ? "section--paper" : ""}">
      <div class="shell">
        <div class="section-heading"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(body)}</p></div>
        <div class="card-grid">${(items || []).map((item, index) => `<article class="card"><span class="card__number">0${index + 1}</span><h3>${escapeHtml(item)}</h3><p>Az oldal ezt a szempontot külön, közérthetően és ellenőrizhető adatokkal bontja ki.</p></article>`).join("")}</div>
      </div>
    </section>`).join("");
  const links = page.links ? `<section class="section"><div class="shell"><div class="section-heading"><h2>Innen érdemes folytatni</h2><p>Válasszátok azt az utat, amelyik a mostani döntésetekhez áll a legközelebb.</p></div><ul class="route-list">${page.links.map(([label, target]) => `<li><a href="${href(target)}" data-route>${escapeHtml(label)}</a></li>`).join("")}</ul></div></section>` : "";
  const quote = page.quote ? `<section class="quote-band"><div class="quote-band__photo"></div><div class="quote-band__copy"><blockquote>${escapeHtml(page.quote[0])}</blockquote><cite>${escapeHtml(page.quote[1])}</cite></div></section>` : "";
  const notice = page.notice ? `<div class="shell"><p class="status-note"><strong>Adat- és kiadási kapu:</strong> ${escapeHtml(page.notice)}</p></div>` : "";
  main.innerHTML = `
    <article data-page-id="${escapeHtml(page.id)}" data-release-state="review-required">
      <section class="hero">
        <div class="hero__copy"><span class="hero__tag">${escapeHtml(page.id)} · szerkesztési előnézet</span><p class="eyebrow">${escapeHtml(page.eyebrow)}</p><h1>${escapeHtml(page.title)}</h1><p class="lede">${escapeHtml(page.intro)}</p><div class="actions">${action(page.primary)}${action(page.secondary, true)}</div></div>
        <div class="hero__media ${mediaClass(page.image)}" role="img" aria-label="Everyday Homes élethelyzet"></div>
      </section>
      <div class="trust-strip"><span>Típusházak</span><span>Tervezés</span><span>Finanszírozási segítség</span><span>Generálkivitelezés</span></div>
      ${notice}${sections}${links}${quote}
      <section class="section section--dark"><div class="shell"><div class="decision-panel"><div><p class="eyebrow">A következő lépés</p><h2>Nem kell ma mindenről dönteni.</h2><p>Elég azt tisztázni, mi visz most közelebb a saját otthonotokhoz.</p></div><div><h3>Otthon – egyszerűen.</h3><div class="actions">${action(page.primary || ["Kezdjük együtt","/kezdjuk-egyutt"], true)}</div></div></div></div></section>
    </article>`;
  setCurrent(path);
  bindRoutes();
}

function setCurrent(path) {
  document.querySelectorAll(".primary-nav a").forEach(link => {
    const target = link.getAttribute("href").replace(BASE, "").replace(/\/$/, "") || "/";
    if (path === target || (target !== "/" && path.startsWith(target))) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
}

function renderNotFound(path) {
  document.querySelector("main").innerHTML = `<section class="not-found"><div><p class="eyebrow">Tartalmi staging</p><h1>Ez az aloldal még nincs ebben a buildben.</h1><p class="lede">A kért útvonal: ${escapeHtml(path)}. A kanonikus tervben szereplő, de még nem implementált oldalak kiadása továbbra is blokkolt.</p><div class="actions"><a class="button" href="${href("/")}" data-route>Vissza a kezdőlapra</a></div></div></section>`;
  bindRoutes();
}

function navigate(path, replace = false) {
  const url = href(path);
  history[replace ? "replaceState" : "pushState"]({}, "", url + (window.location.search || ""));
  const current = normalizePath();
  pages[current] ? renderPage(pages[current], current) : renderNotFound(current);
  window.scrollTo(0, 0);
}

function bindRoutes() {
  document.querySelectorAll("a[data-route]").forEach(link => {
    link.onclick = event => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      const target = link.getAttribute("href").replace(BASE, "").replace(/\/$/, "") || "/";
      navigate(target);
      document.querySelector(".primary-nav")?.classList.remove("is-open");
      document.querySelector(".menu-toggle")?.setAttribute("aria-expanded", "false");
    };
  });
}

document.querySelector(".menu-toggle").addEventListener("click", event => {
  const nav = document.querySelector(".primary-nav");
  const open = nav.classList.toggle("is-open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});
window.addEventListener("popstate", () => pages[normalizePath()] ? renderPage(pages[normalizePath()], normalizePath()) : renderNotFound(normalizePath()));
const initialPath = normalizePath();
pages[initialPath] ? renderPage(pages[initialPath], initialPath) : renderNotFound(initialPath);
