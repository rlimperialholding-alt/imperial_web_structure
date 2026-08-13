const BASE = "/site-preview/everyday-homes";

const pages = {
  "/": {
    id: "EH-HU-001", eyebrow: "Everyday Homes", title: "A saját otthon nem lehet örökké csak terv.",
    intro: "Találjátok meg azt a házat, amelyik illik a családotokhoz, a telketekhez és a lehetőségeitekhez. Segítünk átlátni a választást, a finanszírozást és az építkezés teljes útját.",
    image: "young", primary: ["Megnézem a házakat", "/otthonvalaszto"], secondary: ["Megnézem, mi fér bele", "/keretbol-otthon"],
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
      ["Ezeket érdemes közelebbről megnéznetek", "A javaslatok a családotok igényei és az adott házról rendelkezésre álló, ellenőrzött adatok alapján készülnek. Ha nincs pontos találat, nem erőltetünk rátok rossz választást: megmutatjuk, melyik feltételen érdemes változtatni.", ["Legfeljebb három közeli találat", "Világos különbségek", "Egy kizáró szempont házanként"]],
      ["Egy pillantás, és látszik a lényeg", "A ház neve, bruttó alapterülete, szobaszáma, aktuális nettó ára + ÁFA és építési ideje egy összefüggő egységben jelenik meg. Hiányos vagy nem ellenőrzött adatokkal ház nem kerülhet a javaslatok közé.", ["Azonos szempontok", "Teljes házkép", "Egyértelmű műszaki tartalom"]]
    ]
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
    image: "mother", primary: ["Elmondom, hol tartunk", "/kezdjuk-egyutt"], secondary: ["Megnézem a házakat", "/otthonvalaszto"],
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
    intro: "Egy elkészült otthon vagy egy futó építkezés többet mutat bármely látványtervnél. Csak olyan helyszínt mutatunk meg, amelyhez rendelkezünk a szükséges hozzájárulással.",
    image: "generations", primary: ["Megnéznék egy házat", "/kezdjuk-egyutt"], secondary: ["Családok történetei", "/kozelrol/csaladok-tortenetei"],
    sections: [["Olyat nézzetek meg, ami nektek releváns", "Méret, technológia és készültségi állapot szerint keressük meg a hasznos helyszínt. Nem díszletet mutatunk, hanem olyan részleteket, amelyek segítik a döntést.", ["Elkészült otthon", "Futó építkezés", "Szakmai kérdések a helyszínen"]]]
  },
  "/elso-lepesek": {
    id: "EH-HU-007", eyebrow: "Kérdésből döntés", title: "Előbb a jó kérdést találjátok meg.",
    intro: "A tudástár nem általános cikklista. Minden útmutató egy konkrét családi döntést tesz érthetőbbé, majd a megfelelő számolóhoz vagy következő lépéshez vezet.",
    image: "young", primary: ["A házmérettel kezdem", "/elso-lepesek/mekkora-haz"], secondary: ["A teljes költséget nézem", "/elso-lepesek/teljes-koltseg"],
    links: [["Mekkora házra van szükségetek?", "/elso-lepesek/mekkora-haz"], ["Hogyan spórol egy jó alaprajz?", "/elso-lepesek/jo-alaprajz"], ["Hét telekellenőrzés foglaló előtt", "/elso-lepesek/telekvasarlas"], ["Milyen költség van a ház árán túl?", "/elso-lepesek/teljes-koltseg"], ["Melyik technológia mikor jó?", "/elso-lepesek/technologia-valasztas"], ["Mitől tartható az ütemterv?", "/elso-lepesek/tarthato-utemterv"]],
    sections: [["A válaszok ellenőrizhetők", "Minden szakmai oldalnál látható, mikor ellenőriztük utoljára. Számszerű példát csak friss, visszakereshető számítás alapján mutatunk.", ["Valós kérdés", "Világos módszer", "Használható következő lépés"]]]
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
    sections: [["Hibabejelentés, érthetően", "Megmutatjuk, milyen adat és fotó segíti a gyors kivizsgálást, ki válaszol, hogyan követhető az ügy, és mikor van szükség helyszíni ellenőrzésre.", ["Bejelentés", "Visszaigazolás", "Vizsgálat", "Megoldás és lezárás"]], ["Csak azt ígérjük, amit írásban is vállalunk", "A garancia időtartama, a díjmentes karbantartás és minden műszaki vizsgálat csak a hatályos szerződésben és garanciális feltételekben szereplő tartalom szerint jelenhet meg.", ["Hatályos feltételek", "Egyértelmű többletvállalás", "Dátummal ellátott tájékoztató"]]]
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
houseCollections.forEach(([path,id,eyebrow,title,intro]) => pages[path] = {id,eyebrow,title,intro,image:"young",primary:["Kérek személyes házajánlást","/kezdjuk-egyutt"],sections:[["Mit láttok majd minden háznál?","A ház csak akkor jelenik meg, ha a képe, neve, bruttó alapterülete, hálószobaszáma, aktuális nettó ára + ÁFA és építési ideje egyaránt rendelkezésre áll.",["Teljes házkép","Azonosított alaprajz","Ellenőrzött ár és határidő","Egyetlen házspecifikus előny"]]],notice:"A típusházak adatai később kapcsolódnak ehhez az oldalhoz. Addig nem mutatunk ellenőrizetlen árat, határidőt vagy házadatot."});

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
  "/szamolok/teljes-projektkeret": ["EH-HU-303","Az építkezés teljes költsége","A ház ára csak az egyik sor."],
  "/szamolok/utemterv": ["EH-HU-304","Mikor költözhetünk?","Nem egyetlen dátumot mondunk. Megmutatjuk, mi vezet el odáig."],
  "/szamolok/felujitas-vagy-uj": ["EH-HU-305","Felújítsunk, bővítsünk vagy építsünk újat?","Nem mindig az új ház a jobb döntés. De nem mindig a felújítás az olcsóbb."],
  "/szamolok/energia-es-koltseg": ["EH-HU-306","Építési és fenntartási költség együtt","Amit ma beépítetek, azt évekig fizetitek – vagy élvezitek."],
  "/szamolok/gyors-hazellenorzes": ["EH-HU-307","Melyik ház illik hozzánk?","Hét kérdés. Egy rövidebb, értelmesebb lista."],
  "/mibol-epuljon": ["EH-HU-401","Miből épüljön?","Nem a hangosabb technológia a jobb. Az, amelyik a ti házatokhoz illik."],
  "/biztonsag/vallalasaink": ["EH-HU-601","Mit vállalunk?","Amit vállalunk, annak helye van a szerződésben."],
  "/kozelrol/csaladok-tortenetei": ["EH-HU-606","Családok történetei","Minden ház mögött más döntés volt."]
};
Object.entries(fallbackGroups).forEach(([path,[id,eyebrow,title]]) => pages[path]={id,eyebrow,title,intro:`${title} A válasz mögött külön látszik, mely adat biztos, melyik becslés, és mit kell még a saját helyzetetekben ellenőrizni.`,image:"generations",primary:["Kezdjük a saját helyzetünkkel","/kezdjuk-egyutt"],sections:[["Érthető eredmény, látható feltételekkel",`A „${eyebrow}” kérdésére nem adunk megtévesztő, egyetlen számból álló választ. Megmutatjuk a forrást, a feltételezést, a várható tartományt és a következő szükséges döntést.`,["Forrás és érvényesség","Feltételezések","Bizonytalansági tartomány","Következő döntés"]]],notice:"Az eredmény tájékoztató kiindulópont. Nem keletkeztet automatikus ajánlatot, költözési garanciát vagy finanszírozási ígéretet."});

Object.assign(pages, {
  "/otthonok/minta": {
    id: "EH-HU-003", eyebrow: "Típusház közelről", title: "Ne csak a homlokzatba szeressetek bele.",
    intro: "Egy jó házadatlapból az is kiderül, hogyan élhettek benne, mit tartalmaz az ár, mi változtatható, és milyen telekre illeszthető a terv.",
    image: "young", primary: ["Hasonló házakat keresek", "/otthonvalaszto"], secondary: ["Előbb a keretet nézem", "/keretbol-otthon"],
    sections: [
      ["A lényeg egyetlen áttekinthető egységben", "A ház neve, bruttó alapterülete, szobaszáma, aktuális nettó ára + ÁFA és várható építési ideje egymás mellett jelenik meg. Ami még nem igazolt, azt nem helyettesítjük becsléssel.", [["Alaprajz, ami olvasható", "A helyiségek mérete és kapcsolata mobilon is áttekinthető."], ["Teljes házkép", "A tető és a ház szélei nem maradhatnak le a képről."], ["Ár és műszaki tartalom együtt", "Az összeg csak a hozzá tartozó készültségi szinttel értelmezhető."]]],
      ["Kinek lehet jó ez az otthon?", "Nem általános jelzőket sorolunk. Megmutatjuk, melyik élethelyzetben működik jól az alaprajz, és hol lehet szükség kompromisszumra vagy módosításra.", ["Családi helyzet", "Napi használat", "Telekadottság", "Későbbi változás"]],
      ["Mit alakíthattok rajta?", "Különválasztjuk a választható opciókat, a tervmódosítást és az egyedi újratervezést. Így már a döntés elején látszik, melyik változtatásnak lehet ár- vagy időhatása.", ["Választható opció", "Mérnöki vizsgálatot igényel", "Újratervezést igényel"]]
    ],
    notice: "Ez egy adatlap-sablon. Konkrét házadat, ár és határidő csak jóváhagyott termékrekordból kerülhet bele."
  },
  "/elso-lepesek-hirlevel": {
    id: "EH-HU-012", eyebrow: "A következő jó döntés", title: "Ne több levelet kapjatok. Hanem jobb kapaszkodókat.",
    intro: "Rövid útmutatókat küldünk azokhoz a döntésekhez, amelyek éppen előttetek állnak: telek, alaprajz, teljes keret, technológia és ütemezés.",
    image: "mother", primary: ["Kiválasztom, mi érdekel", "/kezdjuk-egyutt"],
    sections: [
      ["Ti választjátok meg a témát", "Más információ kell annak, aki telket keres, és más annak, aki már a kivitelezési ajánlatokat hasonlítja össze.", [["Telek előtt", "Beépíthetőség, közművek és a foglaló előtti ellenőrzések."], ["Házválasztáskor", "Méret, alaprajz és valóban használt négyzetméterek."], ["Indulás előtt", "Teljes költség, finanszírozás és reális sorrend."]]],
      ["Bármikor leállítható", "A feliratkozás önkéntes. Minden levélből egyértelműen elérhető a leiratkozás, és csak a kiválasztott témákhoz kapcsolódó tartalmat küldünk.", ["Átlátható hozzájárulás", "Nincs kéretlen ajánlat", "Egyszerű leiratkozás"]]
    ],
    notice: "Feliratkozás csak kifejezett hozzájárulással történhet; az adatkezelési tájékoztató elfogadása nem lehet előre bejelölve."
  },
  "/karrier": {
    id: "EH-HU-013", eyebrow: "Karrier", title: "Olyan otthonokat építünk, amelyek mögött jó döntések állnak.",
    intro: "Mérnökök, tervezők, kivitelezési szakemberek és ügyfélkapcsolati munkatársak közös munkája teszi egyszerűbbé az építkezést a családok számára.",
    image: "young", primary: ["Megnézem a nyitott lehetőségeket", "/kezdjuk-egyutt"],
    sections: [
      ["Mit várunk egymástól?", "Pontosságot ott, ahol egy apró hiba is sokat számít. Egyenes kommunikációt ott, ahol döntést kell segíteni. Felelősséget a saját feladatért és tiszteletet a másik szakmája iránt.", ["Szakmai igényesség", "Érthető kommunikáció", "Vállalt felelősség", "Csapatmunka"]],
      ["Milyen munkát érdemes megmutatnod?", "Nem a leghosszabb bemutatkozást keressük. Írd meg, milyen feladatban vagy igazán jó, milyen eredményre vagy büszke, és milyen szerepben tudnál értéket adni.", ["Rövid szakmai bemutatkozás", "Egy konkrét eredmény", "Elérhetőség és munkavégzési lehetőség"]]
    ],
    notice: "Csak ténylegesen jóváhagyott álláshirdetés jelenhet meg nyitott pozícióként."
  },
  "/sajto": {
    id: "EH-HU-014", eyebrow: "Sajtó és médiakapcsolat", title: "Tények, háttéranyagok és szakmai válaszok egy helyen.",
    intro: "Újságíróknak, szerkesztőségeknek és szakmai partnereknek adunk ellenőrizhető információt a családi ház építéséről és az Everyday Homes működéséről.",
    image: "generations", primary: ["Sajtómegkeresést küldök", "/kezdjuk-egyutt"],
    sections: [
      ["Miben tudunk segíteni?", "Szakmai háttérbeszélgetés, technológiai magyarázat, piaci folyamatok értelmezése vagy jóváhagyott képanyag – a kérdéshez illő forrást adjuk.", ["Szakértői megszólalás", "Műszaki háttéranyag", "Jóváhagyott kép és logó", "Cégadatok"]],
      ["A pontosság fontosabb a gyors válasznál", "Árra, határidőre, referenciára vagy jogi vállalásra vonatkozó adat csak ellenőrzött forrásból és kijelölt nyilatkozó jóváhagyásával kerülhet ki.", ["Forrásellenőrzés", "Nyilatkozói jóváhagyás", "Felhasználási feltételek"]]
    ]
  },
  "/technologiak/favazas": {
    id: "EH-HU-402", eyebrow: "Favázas könnyűszerkezet", title: "Pontos előkészítésből gyors, száraz építési folyamat.",
    intro: "A favázas rendszer előnye nem egyetlen anyagban rejlik, hanem az összehangolt szerkezetben, a rétegrendben és a gondos kivitelezésben.",
    image: "young", primary: ["Összehasonlítom a technológiákat", "/mibol-epuljon"],
    sections: [
      ["Mikor lehet jó választás?", "Ha fontos a kiszámítható, szervezett építési folyamat, az energiahatékony rétegrend és a tervhez igazított üzemi előkészítés.", ["Szervezett előkészítés", "Könnyű szerkezet", "Jól tervezhető rétegrend"]],
      ["Mire kell különösen figyelni?", "A faanyag minőségére, a csomópontokra, a páratechnikai rendre, a légzárásra és arra, hogy a kivitelezés minden rétege dokumentált legyen.", ["Nedvességvédelem", "Légzáró csomópontok", "Szerelési fegyelem", "Ellenőrizhető rétegek"]]
    ]
  },
  "/technologiak/tegla": {
    id: "EH-HU-403", eyebrow: "Téglaépítés", title: "Ismert rendszer, jól megtervezve.",
    intro: "A tégla sok család számára megszokott és könnyen érthető választás. A valódi teljesítményt itt is a teljes falszerkezet, a csomópontok és a kivitelezési minőség adja.",
    image: "mother", primary: ["Összehasonlítom a technológiákat", "/mibol-epuljon"],
    sections: [
      ["Mi szólhat mellette?", "Széles körben ismert építési mód, rugalmas alaprajzi lehetőségek és sokféle elérhető kiegészítő rendszer.", ["Ismert anyaghasználat", "Rugalmas tervezés", "Kialakult szakmai gyakorlat"]],
      ["Mitől lesz valóban jó?", "A pontos falazás, a hőhidak kezelése, a megfelelő szigetelés és a szerkezet kiszáradásához igazított ütemezés nem hagyható ki.", ["Csomóponti tervezés", "Nedves technológiai idők", "Hőszigetelési rendszer", "Minőség-ellenőrzés"]]
    ]
  },
  "/technologiak/liapor": {
    id: "EH-HU-404", eyebrow: "Liapor rendszer", title: "Tömör szerkezet, előkészített építési rend.",
    intro: "A könnyű adalékanyagos elemekből készülő rendszer a tömör fal érzetét üzemi előkészítéssel és szervezett helyszíni munkával kapcsolja össze.",
    image: "generations", primary: ["Összehasonlítom a technológiákat", "/mibol-epuljon"],
    sections: [
      ["Milyen célhoz illeszkedhet?", "Ahol fontos a tömör falszerkezet, az előkészített elemek pontossága és a helyszíni szerkezetépítés rövidítése.", ["Előkészített falelemek", "Tömör falszerkezet", "Szervezett szerelés"]],
      ["Mit kell előre lezárni?", "A nyílásokat, gépészeti átvezetéseket, csomópontokat és szállítási-szerelési feltételeket korán kell összehangolni.", ["Gyártmányterv", "Gépészeti egyeztetés", "Daruzási feltételek", "Helyszíni hozzáférés"]]
    ]
  },
  "/technologiak/acelszerkezet": {
    id: "EH-HU-405", eyebrow: "Acélszerkezet", title: "Milliméterekben tervezett váz, rétegenként felépített komfort.",
    intro: "A könnyű acélváz pontosan gyártható és jól szervezhető rendszer. A lakókomfortot a teljes rétegrend, a hőhidak kezelése és a csomóponti fegyelem biztosítja.",
    image: "young", primary: ["Összehasonlítom a technológiákat", "/mibol-epuljon"],
    sections: [
      ["Miért választják?", "Pontos elemek, alacsony szerkezeti tömeg és előre megtervezhető szerelési sorrend teheti vonzóvá.", ["Pontos gyárthatóság", "Könnyű váz", "Száraz szerelés"]],
      ["Hol dől el a minőség?", "A hőhídmegszakításnál, a korrózióvédelemnél, a rögzítéseknél, a burkolati rétegeknél és a gépészeti áttörések kialakításánál.", ["Hőhidak", "Korrózióvédelem", "Rögzítések", "Akusztikai rétegrend"]]
    ]
  },
  "/muszaki-adatok": {
    id: "EH-HU-406", eyebrow: "Rétegrendek és műszaki adatok", title: "Ne csak azt lássátok, miből épül. Azt is, hogyan áll össze.",
    intro: "Fal, födém, tető és padló csak a teljes rétegrenddel értelmezhető. Megmutatjuk a rétegek szerepét, a csomópontokat és az ellenőrizhető teljesítményadatokat.",
    image: "mother", primary: ["Technológiát választok", "/mibol-epuljon"],
    sections: [
      ["Minden rétegnek feladata van", "Külön jelöljük a teherhordást, a hőszigetelést, a lég- és párazárást, a tűzvédelmet, az akusztikát és a felületképzést.", ["Külső fal", "Talajon fekvő padló", "Födém és tető", "Belső válaszfal"]],
      ["Mitől összehasonlítható két megoldás?", "Azonos követelményt és azonos készültségi szintet kell egymás mellé tenni. Egyetlen anyagvastagság önmagában nem mondja meg, milyen lesz a kész ház.", ["Hőtechnikai cél", "Akusztikai cél", "Tűzvédelmi besorolás", "Karbantarthatóság"]]
    ],
    notice: "Konkrét műszaki érték csak jóváhagyott tervből, teljesítménynyilatkozatból vagy hatályos műszaki adatlapból jelenhet meg."
  },
  "/mi-intezzuk/tervezes": {
    id: "EH-HU-501", eyebrow: "Tervezés", title: "A családotok életét tervezzük meg. Nem csak a falakat.",
    intro: "A jó tervben a napi útvonalak, a fények, a tárolás, a későbbi változások és a vállalható költség ugyanannak a döntésnek a részei.",
    image: "mother", primary: ["Elmondom, mire van szükségünk", "/kezdjuk-egyutt"],
    sections: [
      ["Típustervből vagy egyedi tervből?", "Ha egy meglévő ház kis módosítással illik hozzátok, nem kell mindent elölről kezdeni. Ha a telek vagy az élethelyzet különleges, az egyedi tervezés adhat jobb eredményt.", ["Változtatás nélkül", "Ésszerű módosítással", "Egyedi tervezéssel"]],
      ["A költség nem a terv végén jelenik meg", "A méret, a szerkezeti rend, a gépészet és a részletképzés döntéseit folyamatosan össze kell vetni a kerettel.", ["Koncepció", "Költségellenőrzés", "Engedélyezési feladatok", "Kiviteli részletek"]]
    ]
  },
  "/mi-intezzuk/general-kivitelezes": {
    id: "EH-HU-502", eyebrow: "Generálkivitelezés", title: "Egy ház. Egy összehangolt folyamat.",
    intro: "Nem nektek kell szakágakat egyeztetni, anyagokat hajszolni és egymásnak ellentmondó részfeladatokat összerakni. A kivitelezésnek kijelölt felelősei és ellenőrzési pontjai vannak.",
    image: "young", primary: ["Megnézem a teljes folyamatot", "/igy-lesz-egyszeru"],
    sections: [
      ["Mi tartja egyben az építkezést?", "A lezárt műszaki tartalom, a munkaszakaszokra bontott ütemterv, a dokumentált minőség-ellenőrzés és a változtatások következetes kezelése.", ["Műszaki előkészítés", "Szakági sorrend", "Minőség-ellenőrzés", "Átadás"]],
      ["Mikor kell dönteni?", "A burkolatot, szerelvényt vagy gépészeti opciót nem mindegy, mikor választjátok ki. A döntési naptár előre jelzi, mi közeleg és milyen következménye lehet a késésnek.", ["Döntési határidő", "Jóváhagyott választás", "Ár- és időhatás"]]
    ]
  },
  "/mi-intezzuk/finanszirozas": {
    id: "EH-HU-503", eyebrow: "Finanszírozási segítség", title: "A finanszírozás ne az építkezés közben váljon problémává.",
    intro: "A saját forrást, a hitelt, az esetleges támogatást és a kivitelezés fizetési ütemét már a házválasztás előtt össze kell hangolni.",
    image: "senior", primary: ["Átnézem a finanszírozási lépéseket", "/elso-lepesek/finanszirozas-menete"],
    sections: [
      ["Előszűrés még a nagy döntés előtt", "Előbb azt tisztázzuk, milyen havi teher vállalható, mekkora saját forrás áll rendelkezésre, és milyen feltételeket kell még teljesíteni.", ["Saját forrás", "Vállalható havi összeg", "Jogosultsági feltételek", "Biztonsági tartalék"]],
      ["A folyósításnak illeszkednie kell az építéshez", "A banki készültségi szintek, az értékbecslés, az önerő felhasználása és a kivitelezői számlázás sorrendje egyetlen idővonalon legyen látható.", ["Készültségi fok", "Értékbecslés", "Számla és folyósítás", "Következő munkaszakasz"]]
    ],
    notice: "Hitel-, támogatási és törlesztőadat csak hatályos, dátumozott forrásból jelenhet meg. A tájékoztatás nem hitelígéret."
  },
  "/mi-intezzuk/felujitas": {
    id: "EH-HU-504", eyebrow: "Felújítás", title: "A régi házban van még lehetőség? Derítsük ki, mielőtt költötök rá.",
    intro: "A felújítás akkor jó döntés, ha a szerkezet, az alaprajz, az energetika és a teljes költség együtt is indokolja – nem csak azért, mert az indulás olcsóbbnak látszik.",
    image: "generations", primary: ["Összehasonlítom a lehetőségeket", "/szamolok/felujitas-vagy-uj"],
    sections: [
      ["Előbb állapotot mérünk fel", "A falak, a födém, a tető, a nedvesség, a gépészet és az elektromos hálózat rejtett hibái döntően befolyásolhatják a költséget.", ["Szerkezet", "Nedvesség", "Gépészet", "Energetika"]],
      ["Három út kerül egymás mellé", "Megnézzük, mit ad a felújítás, mit old meg a bővítés, és milyen eredményt hozna ugyanebből a teljes keretből egy új otthon.", ["Felújítás", "Bővítés", "Új ház"]]
    ]
  },
  "/mi-intezzuk/tetoter": {
    id: "EH-HU-505", eyebrow: "Tetőtér-beépítés", title: "Új szobák a meglévő házban – ha a szerkezet is készen áll rá.",
    intro: "A tetőtér akkor válik jó lakótérré, ha a hasznos belmagasság, a födém teherbírása, a lépcső, a fény, a nyári hővédelem és a gépészet együtt működik.",
    image: "mother", primary: ["Kérek előzetes megvalósíthatósági vizsgálatot", "/kezdjuk-egyutt"],
    sections: [
      ["Nem minden négyzetméter használható", "A tetősík alatti területből csak az számít valódi lakótérnek, amely kényelmesen megközelíthető, berendezhető, megvilágítható és megfelelő belmagasságú.", ["Hasznos alapterület", "Lépcső helye", "Természetes fény", "Bútorozhatóság"]],
      ["A meglévő házat is vizsgálni kell", "A födém, a tetőszerkezet, az alapozás és a közművek állapota határozza meg, milyen beavatkozás szükséges.", ["Teherbírás", "Szerkezeti megerősítés", "Gépészeti bővítés", "Engedélyezés"]]
    ]
  },
  "/mi-intezzuk/telek-ellenorzes": {
    id: "EH-HU-506", eyebrow: "Telekellenőrzés", title: "A jó telek nem attól jó, hogy szép helyen van.",
    intro: "A foglaló előtt derüljön ki, mit lehet rá építeni, milyen pluszköltséget okozhat, és illik-e hozzá az a ház, amelyet szeretnétek.",
    image: "young", primary: ["Átnézetem a telket", "/kezdjuk-egyutt"],
    sections: [
      ["Hét kérdés, amelyet nem érdemes későbbre hagyni", "Övezet, beépítési mód, megengedett méret, telekszélesség, közmű, terep és talaj – ezek együtt adják a telek valódi lehetőségeit.", ["Helyi szabályok", "Telekgeometria", "Közművek", "Talaj és terep"]],
      ["A házat rá is kell illeszteni", "A bejárat, a benapozás, a kert, az autóelhelyezés és a szomszédos épületek miatt ugyanaz a terv két telken egészen máshogy működhet.", ["Tájolás", "Kertkapcsolat", "Megközelítés", "Szomszédos beépítés"]]
    ],
    notice: "Az előzetes vizsgálat nem helyettesíti a hatósági, geodéziai, talajmechanikai vagy tervezői szakvéleményt."
  },
  "/mi-intezzuk/szemelyes-hazajanlas": {
    id: "EH-HU-507", eyebrow: "Személyes házajánlás", title: "Ne nektek kelljen végignézni minden házat.",
    intro: "A családotok, a telketek, a keretetek és a költözési célotok alapján három olyan lehetőséget mutatunk, amelyet valóban érdemes összehasonlítani.",
    image: "generations", primary: ["Kérem a három javaslatot", "/kezdjuk-egyutt"],
    sections: [
      ["Miből indulunk ki?", "Nem ízléskvízből. A kötelező helyiségek, a napi használat, a telek korlátai és a teljes projektkeret adja a szűrés alapját.", ["Kik költöznek?", "Mi nem maradhat ki?", "Mi fér el a telken?", "Mi vállalható végig?"]],
      ["Mit kaptok a végén?", "Három eltérő kompromisszumot: melyik ad több teret, melyik marad biztonságosabb keretben, és melyik alakítható jobban később.", ["Első javaslat", "Második lehetőség", "Tudatos alternatíva"]]
    ]
  },
  "/biztonsag/atlathato-ar": {
    id: "EH-HU-602", eyebrow: "Átlátható ár", title: "Egy ár csak akkor ér valamit, ha tudjátok, mit kaptok érte.",
    intro: "Az összehasonlítható ajánlatban ugyanaz a terv, készültségi szint, műszaki tartalom és telekfeltétel szerepel. Különben két különböző dolgot hasonlítotok össze.",
    image: "senior", primary: ["Megnézem a teljes keretet", "/keretbol-otthon"],
    sections: [
      ["Mi van benne? Mi nincs benne?", "A tételeket nem apró betűben rejtjük el. Külön látszik az alapcsomag, a választható opció, a telekfüggő költség és az ügyfél külön feladata.", ["Alap műszaki tartalom", "Választható opció", "Telekfüggő tétel", "Külön megrendelés"]],
      ["Mitől változhat az összeg?", "Tervmódosítás, műszaki tartalom, telekadottság vagy késői döntés módosíthatja a költséget. A változás csak dokumentált ár- és időhatással léphet tovább.", ["Mi változik?", "Mennyibe kerül?", "Hat-e a határidőre?", "Ki hagyta jóvá?"]]
    ]
  },
  "/biztonsag/szerzodes": {
    id: "EH-HU-603", eyebrow: "Érthető szerződés", title: "A fontos mondatokat ne a vita napján olvassátok először.",
    intro: "A szerződésből már aláírás előtt ki kell derülnie, mi épül, mennyiért, milyen ütemben, hogyan igazoljuk a teljesítést, és mi történik eltérés esetén.",
    image: "mother", primary: ["Megnézem a vállalások rendszerét", "/biztonsag/vallalasaink"],
    sections: [
      ["Ezeket mindig külön végigvesszük", "A terv és műszaki tartalom, a vállalási ár, a fizetési ütem, a határidők, a változtatás és az átadás szabályai nem maradhatnak általános mondatok.", ["Műszaki melléklet", "Ár és fizetés", "Ütemezés", "Változtatás és átadás"]],
      ["A jóváhagyás emberi döntés", "Szerződésmódosítást, felelősségelismerést, teljesítésigazolást vagy külső kötelezettségvállalást a rendszer nem végezhet automatikusan.", ["Átolvasás", "Kérdések tisztázása", "Emberi jóváhagyás"]]
    ],
    notice: "A végleges szerződéses tájékoztató csak jogi jóváhagyás után publikálható; ez az oldal nem minősül szerződéses ajánlatnak."
  },
  "/biztonsag/projektkovetes": {
    id: "EH-HU-604", eyebrow: "Projektkövetés", title: "Ne találgassátok, hol tart a házatok.",
    intro: "Az építkezés fő szakaszai, az elkészült munkák, a következő döntések és a jóváhagyott változtatások egy helyen követhetők.",
    image: "young", primary: ["Megnézem a kivitelezés menetét", "/igy-lesz-egyszeru"],
    sections: [
      ["Ami minden héten számít", "Rövid állapotjelentés, fényképes dokumentáció, következő mérföldkő és az ügyfél előtt álló döntés – felesleges műszaki zaj nélkül.", ["Elkészült", "Folyamatban", "Következik", "Döntést igényel"]],
      ["A változásnak nyoma van", "A jóváhagyott módosításnál együtt látszik a kérés, a műszaki megoldás, az árhatás, az időhatás és az elfogadás.", ["Kérés", "Műszaki válasz", "Költség és idő", "Jóváhagyás"]]
    ]
  },
  "/kozelrol/elkeszult-otthonok": {
    id: "EH-HU-605", eyebrow: "Elkészült otthonok", title: "Nézzetek meg egy házat, ahol már zajlik az élet.",
    intro: "Az alaprajz másképp érthető, ha be lehet járni. Megmutatjuk, milyen a tér aránya, a fény, a tárolás és a kertkapcsolat a valóságban.",
    image: "generations", primary: ["Szeretnék házat látogatni", "/kezdjuk-egyutt"],
    sections: [
      ["A hozzátok hasonló házat keressük", "Nem a leglátványosabb helyszín a leghasznosabb. Méret, alaprajz, technológia és készültség alapján választunk olyan referenciát, amelyből valóban tanulhattok.", ["Hasonló méret", "Hasonló élethelyzet", "Releváns technológia", "Használható tapasztalat"]],
      ["A tulajdonos nyugalma első", "Cím, időpont, fénykép és személyes történet csak előzetes, dokumentált hozzájárulással jelenhet meg vagy adható át.", ["Jóváhagyott látogatás", "Egyeztetett kérdések", "Adatvédelem"]]
    ]
  },
  "/biztonsag/atadas-utan": {
    id: "EH-HU-607", eyebrow: "Átadás után", title: "A beköltözés nem a kapcsolat vége.",
    intro: "Megmutatjuk, hogyan jelentsétek be a kérdést vagy hibát, mit érdemes rendszeresen ellenőrizni, és mely karbantartás segít megőrizni az otthon állapotát.",
    image: "senior", primary: ["Megnézem a garanciák rendszerét", "/garanciak-es-utogondozas"],
    sections: [
      ["Hibabejelentés, követhetően", "Egyértelmű visszaigazolás, kijelölt felelős, szükség esetén helyszíni vizsgálat és dokumentált lezárás tartja átláthatóan az ügyet.", ["Bejelentés", "Első válasz", "Vizsgálat", "Javítás és lezárás"]],
      ["A háznak is van használati rendje", "A szellőztetés, a gépészeti rendszerek, a nyílászárók, a csapadékvíz-elvezetés és a felületek karbantartása közös érdeket szolgál.", ["Évszakos ellenőrzés", "Karbantartási napló", "Szakembert igénylő feladat"]]
    ]
  },
  "/elso-lepesek/finanszirozas-menete": {
    id: "EH-HU-706", eyebrow: "Önerő, hitel és folyósítás", title: "A pénznek akkor kell megérkeznie, amikor az építkezésnek szüksége van rá.",
    intro: "A finanszírozás menete akkor biztonságos, ha a saját forrás, az értékbecslés, a banki készültségi szintek és a kivitelezési fizetések ugyanarra az idővonalra kerülnek.",
    image: "senior", primary: ["Átnézem a saját keretünket", "/szamolok/teljes-projektkeret"],
    sections: [
      ["Milyen sorrendre számítsatok?", "Pénzügyi előszűrés, dokumentumok, értékbecslés, szerződés, saját forrás felhasználása, készültségi ellenőrzések és szakaszos folyósítás.", ["Előszűrés", "Dokumentumok", "Értékbecslés", "Folyósítás"]],
      ["Hol szokott megakadni a folyamat?", "Hiányzó irat, eltérő költségvetés, nem igazolt készültség vagy rosszul időzített számla késleltetheti a következő szakaszt.", ["Dokumentumlista", "Egyező költségvetés", "Készültség igazolása", "Időben kiállított számla"]]
    ],
    notice: "A támogatások és banki feltételek változhatnak. Csak hatályos, dátumozott adatok alapján szabad konkrét összeget vagy jogosultságot közölni."
  },
  "/elso-lepesek/energia": {
    id: "EH-HU-708", eyebrow: "Szigetelés és gépészet", title: "Ne külön válasszatok szigetelést és gépészetet. Egy házat kell működtetni.",
    intro: "A falak, nyílászárók, légzárás, árnyékolás, fűtés, hűtés és szellőzés együtt határozza meg a komfortot és a várható üzemeltetést.",
    image: "mother", primary: ["Építési és fenntartási költséget hasonlítok", "/szamolok/energia-es-koltseg"],
    sections: [
      ["Előbb a ház hőigényét csökkentjük", "A tájolás, a kompakt forma, a hőhidak, a légzárás és a nyári árnyékolás sokszor fontosabb, mint egy önmagában drágább gépészeti berendezés.", ["Tájolás", "Hőszigetelés", "Légzárás", "Árnyékolás"]],
      ["Utána választunk gépészetet", "A rendszer mérete, szabályozhatósága, karbantartása és várható fogyasztása ugyanúgy számít, mint a beruházási költség.", ["Fűtés és hűtés", "Meleg víz", "Szellőzés", "Szabályozás"]]
    ]
  },
  "/adatkezeles": {
    id: "EH-HU-901", eyebrow: "Adatkezelés", title: "Tudjátok, milyen adatot miért kérünk.",
    intro: "Az adatkezelési tájékoztató külön kezeli a kapcsolatfelvételt, az ajánlatkérést, a hírlevelet, az időpontfoglalást és a későbbi ügyfélkapcsolatot.",
    image: "young", primary: ["Kapcsolatfelvétel", "/kezdjuk-egyutt"],
    sections: [
      ["Minden cél külön érthető", "Megnevezzük az adatkezelés célját, jogalapját, az adatok körét, a megőrzési időt, a címzetteket és az érintetti jogokat.", ["Miért kérjük?", "Meddig őrizzük?", "Ki férhet hozzá?", "Milyen jogotok van?"]],
      ["A hozzájárulás nem lehet elrejtve", "A hírlevél és más választható kommunikáció külön, önkéntes döntés. A szolgáltatás igénybevételét nem kötjük szükségtelen marketing-hozzájáruláshoz.", ["Külön jelölőnégyzet", "Nincs előre bejelölve", "Bármikor visszavonható"]]
    ],
    notice: "A végleges szöveg az adatkezelő és adatfeldolgozók hiteles adatai, valamint jogi jóváhagyás nélkül nem publikálható."
  },
  "/impresszum": {
    id: "EH-HU-902", eyebrow: "Impresszum", title: "Ki felel az oldalért? Itt legyen egyértelmű.",
    intro: "A szolgáltató azonosító adatai, hivatalos elérhetőségei, nyilvántartási adatai és a tárhelyszolgáltató információi egy helyen jelennek meg.",
    image: "generations", primary: ["Kapcsolat", "/kezdjuk-egyutt"],
    sections: [
      ["Kötelező azonosító adatok", "A végleges oldalon csak a hivatalos nyilvántartással egyező cégnév, székhely, cégjegyzékszám, adószám és elérhetőség szerepelhet.", ["Szolgáltató", "Nyilvántartási adatok", "Elérhetőség", "Tárhelyszolgáltató"]]
    ],
    notice: "Az üres vagy nem igazolt cégadatot tilos feltételezett adattal pótolni."
  },
  "/sutik": {
    id: "EH-HU-903", eyebrow: "Sütik és hozzájárulás", title: "Ti döntitek el, mi futhat a böngészőtökben.",
    intro: "A működéshez szükséges elemeket különválasztjuk a mérési és marketingcélú technológiáktól. A választható kategóriák csak hozzájárulás után indulhatnak el.",
    image: "mother", primary: ["Beállítások áttekintése", "/adatkezeles"],
    sections: [
      ["Egyszerű választás, valódi hatással", "Az elfogadás és az elutasítás azonosan könnyen elérhető. A választás később bármikor módosítható.", ["Szükséges", "Mérés", "Személyre szabás", "Marketing"]],
      ["A lista legyen naprakész", "Minden alkalmazott technológiánál megnevezzük a szolgáltatót, a célt, az élettartamot és azt, hogy kerül-e adat harmadik félhez.", ["Név és szolgáltató", "Cél", "Lejárat", "Adattovábbítás"]]
    ],
    notice: "Nem szükséges süti vagy követőkód hozzájárulás előtt nem tölthető be."
  },
  "/akadalymentesseg": {
    id: "EH-HU-904", eyebrow: "Akadálymentesség", title: "Az információ akkor ér valamit, ha el is lehet érni.",
    intro: "A weboldalt billentyűzettel, képernyőolvasóval és nagyított nézetben is használhatóra tervezzük, és folyamatosan javítjuk a feltárt akadályokat.",
    image: "senior", primary: ["Akadályt jelzek", "/kezdjuk-egyutt"],
    sections: [
      ["Mire figyelünk?", "Érthető címsorrend, látható fókusz, megfelelő kontraszt, szöveges képjelentés, feliratozott űrlap és kiszámítható navigáció segíti a használatot.", ["Billentyűzet", "Képernyőolvasó", "Kontraszt", "Nagyított nézet"]],
      ["Ha valami mégsem működik", "A bejelentésben elég megírni az oldal címét, a tapasztalt akadályt és a használt eszközt. A visszajelzést kivizsgáljuk és követhetően kezeljük.", ["Oldal vagy funkció", "Tapasztalt akadály", "Eszköz vagy böngésző"]]
    ]
  }
});

function normalizePath() {
  let path = window.location.pathname.replace(/\/+$/, "") || "/";
  if (path.startsWith(BASE)) path = path.slice(BASE.length) || "/";
  return path;
}

function href(path) { return path === "/" ? `${BASE}/` : `${BASE}${path}`; }
function mediaClass(image) { return image === "generations" ? "hero__media--generations" : image === "mother" ? "hero__media--mother" : image === "senior" ? "hero__media--senior" : ""; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char])); }

function renderPage(page, path) {
  document.title = `${page.eyebrow} | Everyday Homes`;
  const main = document.querySelector("main");
  const action = (item, secondary = false) => item ? `<a class="button${secondary ? " button--secondary" : ""}" href="${href(item[1])}" data-route>${escapeHtml(item[0])}</a>` : "";
  const sections = (page.sections || []).map(([title, body, items], sectionIndex) => `
    <section class="section ${sectionIndex % 2 === 0 ? "section--paper" : ""}">
      <div class="shell">
        <div class="section-heading"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(body)}</p></div>
        <div class="card-grid">${(items || []).map((item, index) => {
          const cardTitle = Array.isArray(item) ? item[0] : item;
          const cardBody = Array.isArray(item) ? item[1] : "";
          return `<article class="card"><span class="card__number">${String(index + 1).padStart(2, "0")}</span><h3>${escapeHtml(cardTitle)}</h3>${cardBody ? `<p>${escapeHtml(cardBody)}</p>` : ""}</article>`;
        }).join("")}</div>
      </div>
    </section>`).join("");
  const links = page.links ? `<section class="section"><div class="shell"><div class="section-heading"><h2>Innen érdemes folytatni</h2><p>Válasszátok azt az utat, amelyik a mostani döntésetekhez áll a legközelebb.</p></div><ul class="route-list">${page.links.map(([label, target]) => `<li><a href="${href(target)}" data-route>${escapeHtml(label)}</a></li>`).join("")}</ul></div></section>` : "";
  const quote = page.quote ? `<section class="quote-band"><div class="quote-band__photo"></div><div class="quote-band__copy"><blockquote>${escapeHtml(page.quote[0])}</blockquote><cite>${escapeHtml(page.quote[1])}</cite></div></section>` : "";
  main.innerHTML = `
    <article>
      <section class="hero">
        <div class="hero__copy"><span class="hero__tag">Otthon – egyszerűen.</span><p class="eyebrow">${escapeHtml(page.eyebrow)}</p><h1>${escapeHtml(page.title)}</h1><p class="lede">${escapeHtml(page.intro)}</p><div class="actions">${action(page.primary)}${action(page.secondary, true)}${action(["Beszéljünk a terveitekről", "/kezdjuk-egyutt"], true)}</div></div>
        <div class="hero__media ${mediaClass(page.image)}" role="img" aria-label="Everyday Homes élethelyzet"></div>
      </section>
      <div class="trust-strip"><span>Több mint 300 típusterv</span><span>Személyes házajánlás</span><span>Átlátható feltételek</span><span>Tervezéstől az átadásig</span></div>
      ${sections}${links}${quote}
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
  document.querySelector("main").innerHTML = `<section class="not-found"><div><p class="eyebrow">Az oldal nem található</p><h1>Ezt az aloldalt most nem tudjuk megmutatni.</h1><p class="lede">A kért cím: ${escapeHtml(path)}. Válasszatok a menüből, vagy térjetek vissza a kezdőlapra.</p><div class="actions"><a class="button" href="${href("/")}" data-route>Vissza a kezdőlapra</a></div></div></section>`;
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
      document.querySelectorAll(".nav-group[open]").forEach(group => group.removeAttribute("open"));
    };
  });
}

document.querySelector(".menu-toggle").addEventListener("click", event => {
  const nav = document.querySelector(".primary-nav");
  const open = nav.classList.toggle("is-open");
  event.currentTarget.setAttribute("aria-expanded", String(open));
});
document.addEventListener("click", event => {
  if (!event.target.closest(".primary-nav")) {
    document.querySelectorAll(".nav-group[open]").forEach(group => group.removeAttribute("open"));
  }
});
window.addEventListener("popstate", () => pages[normalizePath()] ? renderPage(pages[normalizePath()], normalizePath()) : renderNotFound(normalizePath()));
const initialPath = normalizePath();
pages[initialPath] ? renderPage(pages[initialPath], initialPath) : renderNotFound(initialPath);
