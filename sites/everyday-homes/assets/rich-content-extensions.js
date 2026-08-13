/* A Drive-ból importált, jóváhagyott törzsszövegek változatlan kiegészítő rétege. */
(function registerRichContentExtensions() {
  const faqBlocks = pairs => pairs.flatMap(([question, answer]) => [question, answer]);
  const section = (title, blocks) => ({ title, blocks });
  const faqSection = (title, pairs) => section(title, faqBlocks(pairs));

  globalThis.RICH_CONTENT_EXTENSIONS = {
    "/": [
      section("EGY OTTHON, AMELYIK A TI NAPJAITOKHOZ IGAZODIK", [
        "Nem négyzetmétert szeretnétek, hanem egy helyet, ahol a reggel nem kerülgetéssel kezdődik, délután jut tér a játékra, este pedig mindenki megtalálja a saját nyugalmát. Az Everyday Homes ezért nem egyetlen divatos alaprajzot próbál mindenkire rábeszélni. Abból indulunk ki, hogyan éltek most, mi változik a következő években, és milyen havi teher mellett marad biztonságban a család megszokott élete.",
        "A választás akkor lesz egyszerű, ha egyszerre látjátok a ház használhatóságát, a telek adottságait és a teljes projekt pénzügyi határát. Egy látványos nappali önmagában kevés. Tudni kell, hová kerül a kabát, elfér-e a babakocsi, lehet-e csendben dolgozni, milyen útvonalon érkezik a bevásárlás, és marad-e tartalék a költözés utáni első hónapokra.",
        "Az oldalon található útmutatók nem helyettesítik a helyszíni vizsgálatot, a pénzügyi tanácsadást vagy a tételes ajánlatot. Arra valók, hogy már az első beszélgetésre jobb kérdésekkel érkezzetek, és gyorsabban kiderüljön, melyik irány szolgálja valóban a családotokat."
      ]),
      faqSection("AMIT AZ ELSŐ VÁLASZTÁS ELŐTT ÉRDEMES TISZTÁZNI", [
        ["Mivel kezdjünk, ha még csak az otthon gondolata van meg?", "Írjátok össze, hányan költöznétek, mely napi helyzetek szűkösek most, milyen térségben keresnétek telket, és mekkora teljes havi terhet viselnétek nyugodtan. Ebből már kialakul egy használható első irány."],
        ["A több négyzetméter mindig kényelmesebb otthont jelent?", "Nem. A közlekedők, rosszul bútorozható sarkok és túlméretezett helyiségek drágák, mégsem feltétlenül segítik a mindennapokat. A jól kapcsolódó, valóban használt terek gyakran többet adnak."],
        ["Mikor érdemes telket keresni a ház kiválasztásához képest?", "A két döntést egymással párhuzamosan érdemes előkészíteni. Egy kedvelt ház segít megérteni a telekigényt, a telek szabályai pedig megmutatják, milyen épület fér el rajta."],
        ["Mit jelent nálatok az, hogy Otthon – egyszerűen?", "Azt, hogy a bonyolult döntéseket érthető sorrendbe rendezzük. Nem ígérjük, hogy egy építkezés kérdések nélküli, de minden szakaszban láthatóvá tesszük a következő feladatot és annak feltételeit."],
        ["Hogyan derül ki, melyik alaprajz illik hozzánk?", "A szobaszám mellett a napi útvonalakat, a tárolási igényt, a munkát, a vendégeket, a kertkapcsolatot és a következő évek várható változásait is végig kell venni."],
        ["Érdemes a jelenlegi vagy a jövőbeli életünkre méretezni?", "A belátható változásokra érdemes felkészülni, de minden bizonytalan lehetőségre külön helyiséget építeni pazarló lehet. A rugalmasan használható terek jobb egyensúlyt adhatnak."],
        ["Mi legyen előbb: a kívánságlista vagy a pénzügyi keret?", "Mindkettő kell, de két külön lapon. Előbb írjátok le, mire vágytok, majd jelöljétek, mi nélkülözhetetlen, mi alakítható és mi hagyható későbbre. Ezután illesszétek a teljes projektkerethez."],
        ["Miért nem elég csak a ház feltüntetett árával számolni?", "A telek, a helyszíni előkészítés, a közművek, a külső munkák, a választott műszaki tartalom és a költözés költsége külön tétel lehet. A biztonságos terv ezeket is láthatóvá teszi."],
        ["Mennyi tartalékot hagyjunk az építkezés mellett?", "Nincs minden családra érvényes százalék. A tartalékot a telek ismert és nyitott kockázatai, a finanszírozás, a műszaki döntések és a háztartás biztonsági igénye alapján kell meghatározni."],
        ["Segít a rendszer akkor is, ha nem értünk az építéshez?", "Igen, az útmutatók hétköznapi kérdésekből indulnak. A műszaki döntést azonban mindig a konkrét telek, terv és dokumentált műszaki tartalom alapján, szakemberrel kell lezárni."],
        ["Miért fontos már korán beszélni a tárolásról?", "Mert a rendezettséget nem utólag vásárolt szekrények, hanem jól elhelyezett tárolók adják. A bejárat, a konyha, a háztartási tér és a szezonális holmik helye alaprajzi kérdés."],
        ["Kell külön dolgozószoba, ha csak néha dolgozunk otthon?", "Nem feltétlenül. Lehet jól zárható fülke, vendégszobával közös funkció vagy csendes galéria. A döntést a hívások gyakorisága, a zaj és a tárolás határozza meg."],
        ["Hogyan gondoljunk a kertre a ház kiválasztásakor?", "Ne csak a kert méretét nézzétek. Fontos, melyik helyiségből érhető el, hol lesz árnyék, merre néz a terasz, hová kerülhet autó, tároló és játszófelület."],
        ["Miért számít a bútorozhatóság már a terven?", "A nyílászárók, közlekedési sávok és falfelületek eldöntik, elfér-e a valódi ágy, asztal vagy szekrény. A berendezési próba gyorsan leleplezi a papíron nagynak tűnő, mégis nehezen használható szobát."],
        ["Mikor jó döntés egy kisebb ház?", "Akkor, ha minden fontos élethelyzetnek jut kényelmes hely, a tárolás megoldott, és a kisebb fenntartási vagy finanszírozási teher több szabadságot hagy a családnak."],
        ["Hogyan készülhetünk fel az első konzultációra?", "Hozzatok telekadatot, ha van, néhány kedvelt alaprajzot, a kötelező helyiségek listáját, a teljes keret nagyságrendjét és három kérdést, amelyre mindenképp választ szeretnétek."],
        ["Kapunk rögtön végleges árat az első beszélgetésen?", "Végleges ár csak az ellenőrzött telekadatok, a rögzített terv, a választott készültségi szint és műszaki tartalom alapján adható. Az első beszélgetés az ehhez szükséges hiányokat tisztázza."],
        ["Miért jó, ha a házválasztásnál a gyerekek napját is végignézzük?", "Mert a bejárat, a tanulás, a játék, a fürdés és az elcsendesedés útvonala megmutatja, hol lesz ütközés vagy fölösleges kerülő a hétköznapokban."],
        ["Lehet úgy tervezni, hogy később változzon a család összetétele?", "Igen. A könnyen leválasztható tér, a jó helyen lévő vizes kiállás vagy egy semleges arányú szoba többféle jövőbeli használatot engedhet nagy bontás nélkül."],
        ["Mitől lesz egy választás valóban összehasonlítható?", "Azonos készültségi szintet, azonos műszaki határt, azonos telekfeltételeket és az árban benne lévő, illetve külön fizetendő tételeket kell egymás mellé tenni."],
        ["Mikor érdemes személyesen megnézni egy elkészült otthont?", "Amikor már tudjátok, mely térkapcsolatok érdekelnek. Így nemcsak a felületeket nézitek, hanem azt is, milyen széles a közlekedő, mekkora a valós nappali és hogyan érkezik a fény."],
        ["Mi legyen, ha a családtagok mást tartanak fontosnak?", "Mindenki nevezzen meg három nélkülözhetetlen igényt és három engedményt. A közös metszetből, nem pedig a leghangosabb kívánságból érdemes alaprajzi sorrendet készíteni."],
        ["A technológiát vagy az alaprajzot válasszuk ki előbb?", "Az életmód és a telek adja az alaprajzi szükségletet, a teljesítményelvárás és a projekt feltételei pedig a technológiai irányt. A kettőt össze kell hangolni, nem egymástól elszigetelten választani."],
        ["Mikor mondható ki, hogy készen állunk a következő lépésre?", "Ha a telek helyzete ismert, az alaprajzi igények rangsoroltak, a teljes keretnek van határa, és le tudjátok írni, mely kérdésekhez kell még szakmai vizsgálat."],
        ["Mi történik, ha az első választásunk nem fér bele a keretbe?", "Nem egyszerűen olcsóbb burkolatokat keresünk. Először a méretet, a térkapcsolatokat, a telekhez kötődő tételeket és a későbbre halasztható elemeket vizsgáljuk meg, hogy az otthon lényege megmaradjon."]
      ]),
      section("AMIÉRT ÉRDEMES MOST ELINDULNI", [
        "A jó otthonválasztás nem elvesz a család terveiből, hanem rendet tesz közöttük. Amikor már külön látjátok a valódi szükségletet, a szép, de nélkülözhető ötletet és a még ellenőrizendő feltételt, könnyebb lesz nemet mondani a rossz kompromisszumra és igent mondani arra a házra, amelyben valóban el tudjátok képzelni a hétköznapjaitokat.",
        "Nem kell mindent egy délután alatt eldönteni. Elég, ha a következő döntéshez szükséges adatokat összegyűjtitek, a családi prioritásokat kimondjátok, és nem hagyjátok, hogy egy látványos részlet elterelje a figyelmet az egész otthon működéséről. Így a választás nem fárasztó háznézegetés, hanem egyre tisztább közös terv lesz."
      ])
    ],

    "/otthonvalaszto": [
      faqSection("A SZŰRÉS UTÁN FELMERÜLŐ KÉRDÉSEK", [
        ["Miért élethelyzettel kezdődik a választás?", "Mert ugyanaz a szobaszám mást jelent egy kisgyerekes családnak, egy otthon dolgozó párnak vagy két együtt élő generációnak. Az élethelyzet megmutatja a fontos térkapcsolatokat."],
        ["Mit tegyünk, ha két ajánlott otthon is tetszik?", "Ne a homlokzattal döntsetek. Rajzoljátok végig egy hétköznapot mindkét alaprajzon, helyezzétek el a valódi bútorokat, majd hasonlítsátok össze a teljes projekt várható feltételeit."],
        ["A találati sorrend ajánlásnak számít?", "A sorrend tájékozódási segítség, nem mérnöki vagy pénzügyi döntés. A végső megfelelést telekillesztés, műszaki egyeztetés és tételes számítás igazolja."],
        ["Miért kérdez a választó a havi teherről?", "Az otthon ára csak az egyik szám. Fontos, hogy a finanszírozás mellett maradjon mozgástér a család életére, fenntartásra, váratlan kiadásokra és a költözésre is."],
        ["Megadhatunk hozzávetőleges adatokat?", "Igen, a korai szűréshez becslés is elég, de ezt egyértelműen jelölni kell. A bizonytalan adatból nem lesz végleges ajánlat vagy vállalás."],
        ["Miért kérdez a rendszer a telek lejtéséről?", "A lejtés befolyásolhatja az alapozást, a megközelítést, a vízelvezetést és az épület elhelyezését. Emiatt ugyanaz a ház két telken eltérő projektet jelenthet."],
        ["Mit jelent, hogy egy ház jól bővíthető?", "A későbbi bővítés helye, szerkezeti csatlakozása, tetőkapcsolata és gépészeti lehetősége már az első ütemben átgondolható. Ez nem automatikus ígéret, hanem tervezési szempont."],
        ["Kizárhatunk olyan alaprajzot, amelyben nincs külön kamra?", "Igen, de előtte érdemes megnézni, megoldható-e a szükséges tárolás magas szekrénnyel, háztartási helyiséggel vagy közeli, jól szervezett tárolófallal."],
        ["Hogyan kezeljük a vendégszoba kérdését?", "Gondoljátok végig, évente hány éjszakára kell, és milyen más funkcióval osztható meg. Egy ritkán használt külön szoba helyett lehet dolgozó, hobbitér vagy többcélú helyiség."],
        ["Miért fontos az egyszintes vagy többszintes forma korai eldöntése?", "A telek mérete, a lépcső mindennapi használata, a család életkora, a kertkapcsolat és a kivitelezési összefüggések mind eltérnek. Ez alapvető irány, nem puszta ízlés."],
        ["A választó figyelembe veszi a tájolást?", "A tájolás végleges értékelése telekhez kötött. A szűrés jelezheti a kívánt fény- és kertkapcsolatot, de a tényleges elhelyezést helyszíni és szabályozási adatok alapján kell megoldani."],
        ["Mikor kell dönteni a gépészetről?", "A pontos rendszer később rögzíthető, de a helyigényt, a teljesítménycélt, az energiaellátást és a fő nyomvonalakat időben össze kell hangolni az alaprajzzal."],
        ["Miért nincs minden háznál ugyanaz az építési idő?", "A telek, az engedélyezési helyzet, a tervváltozás, a technológia, a műszaki tartalom és a kapacitás eltérő. Időpont csak ezek tisztázása után vállalható."],
        ["Hogyan hasonlítsuk össze a bruttó és a nettó alapterületet?", "Előbb tisztázzátok, mit tartalmaz az adott mérőszám. Utána a használható helyiségeket és a falak, közlekedők arányát is nézzétek, ne csak egyetlen összesített számot."],
        ["Elmenthető a család közös listája?", "A személyes mentés a későbbi ügyfélfiókban lesz elérhető. Addig a kiválasztott oldalak hivatkozásait közös jegyzetben tudjátok megőrizni."],
        ["Miért nem kér a választó rögtön nevet és telefonszámot?", "Előbb szeretnénk valódi értéket adni a tájékozódáshoz. Kapcsolati adatot csak akkor indokolt kérni, amikor visszahívást, ajánlatot vagy személyes segítséget kértek."],
        ["Mit tegyünk, ha a telkünkre egyik találat sem illeszkedik?", "Telekellenőrzéssel tisztázni kell a korlátot. Lehet, hogy más tájolás, tömegforma vagy házméret szükséges, és az is lehet, hogy egyedi tervezés a felelős út."],
        ["Hogyan számít a háztartási helyiség a választásnál?", "Nem luxus, hanem napi munkatér lehet. A mosás, szárítás, takarítóeszközök és gépészet rendezett helye tehermentesítheti a fürdőt és a közös tereket."],
        ["A gyerekek külön szobája mindig elsődleges?", "A család életkorától, időtávjától és keretétől függ. Néha a kezdetben közös szoba és később leválasztható tér ad jobb, biztonságosabb megoldást."],
        ["Milyen széles közlekedőt keressünk?", "Nincs önmagában jó szám: a nyíló ajtók, a bútorok mozgatása, a babakocsi, az akadálymentes használat és a csomópontok együtt számítanak. A tervet berendezve kell ellenőrizni."],
        ["Hogyan kerülhetjük el, hogy csak a látvány döntsön?", "A kedvelt kép mellé tegyetek három bizonyítékot: berendezett alaprajzot, tételes műszaki tartalmat és a telekre vonatkozó illesztési vizsgálatot."],
        ["Miért kell megadni, mikor szeretnénk költözni?", "A kívánt időpont visszafelé megmutatja, mikor kell lezárni a telek, terv, finanszírozás és szerződés kérdéseit. Ez még nem vállalt határidő, hanem tervezési támpont."],
        ["Kérhetünk segítséget a három legjobb találat átbeszéléséhez?", "Igen. A beszélgetés akkor hasznos, ha elmondjátok, miért tetszik vagy mi zavar az egyes alaprajzokban, és milyen telek- vagy pénzügyi adat áll már rendelkezésre."],
        ["Mi alapján vessünk el egy egyébként szép házat?", "Ha nem fér el szabályosan a telken, szétesik benne a napi élet, a teljes költsége nem tartható, vagy csak sok drága módosítással felelne meg, érdemes másik tervet választani."],
        ["Mi a jó eredménye az Otthonválasztónak?", "Nem feltétlenül egyetlen ház. Jó eredmény az is, ha három reális irány marad, ismertté válnak a döntő különbségek, és világos, mely adatot kell még ellenőrizni."]
      ])
    ],

    "/keretbol-otthon": [
      section("A KERET NEM KORLÁT, HANEM DÖNTÉSI SORREND", [
        "A biztonságos projektkeret nem azt jelenti, hogy minden forintot a házra költötök. A család mindennapi működésének, a telekhez kapcsolódó feladatoknak, a költözésnek és a valóban váratlan helyzeteknek is helyet kell hagyni. Az első szám ezért nem egy reklámban látott négyzetméterár, hanem az az összeg és havi teher, amely mellett továbbra is nyugodtan tudtok élni.",
        "A költségek három csoportban lesznek átláthatók: ami a rögzített háztartalomhoz tartozik; ami a helyszín és az előkészítés miatt külön vizsgálandó; valamint ami választás vagy későbbi döntés eredménye. Ha ezeket összekeverjük, egy kedvezőnek látszó kezdőár könnyen félrevezet. Ha külön kezeljük őket, látszik, hol lehet értelmesen egyszerűsíteni, és mely tételen nem érdemes kockáztatni.",
        "A kalkuláció tájékozódási eszköz. A hitelképességet pénzügyi szakember, a helyszíni költséget vizsgálat, a kivitelezési árat pedig rögzített terv és tételes műszaki tartalom alapján lehet lezárni."
      ]),
      faqSection("PÉNZÜGYI KÉRDÉSEK, AMELYEKET NEM ÉRDEMES KÉSŐBBRE HAGYNI", [
        ["A teljes keretbe beleszámít a telek ára is?", "Igen, ha a telek még nincs meg. Ha már a tulajdonotokban van, akkor is számolni kell a kapcsolódó vizsgálatokkal, közművekkel, tereprendezéssel és egyéb helyszíni tételekkel."],
        ["Miért kell külön kezelni a ház árát és a külső munkákat?", "Mert a kerítés, burkolt felületek, kert, kapu, támfal vagy hosszú közműbekötés nem feltétlenül része a ház készültségi szintjének, mégis pénz és idő kell hozzá."],
        ["Mitől lesz tartható egy havi teher?", "Nem a banki maximumtól. A család biztos jövedelmét, meglévő kiadásait, várható élethelyzet-változásait, tartalékát és kockázattűrését együtt kell mérlegelni."],
        ["Hogyan számoljunk változó kamatozású finanszírozással?", "A jelenlegi részlet önmagában kevés. Kérjetek több forgatókönyvet, és nézzétek meg azt is, hogyan hatna a családi költségvetésre kedvezőtlenebb kamat- vagy jövedelmi helyzet."],
        ["Mire jó a biztonsági tartalék?", "Arra, hogy egy előre nem látható, de indokolt tétel ne kényszerítsen rossz műszaki kompromisszumra, sürgős hitelre vagy a család mindennapi pénzügyi biztonságának feladására."],
        ["A telek olcsó ára jelenthet olcsóbb projektet?", "Nem feltétlenül. A nehéz megközelítés, rossz talaj, nagy szintkülönbség, hiányzó közmű vagy korlátozó szabályozás jelentős többletet okozhat. A teljes hatást kell vizsgálni."],
        ["Hol lehet a legkevesebb veszteséggel csökkenteni a keretet?", "Gyakran a felesleges alapterület, a sok törés, a bonyolult tető, a későn kért változtatás és a párhuzamos funkciók felülvizsgálata hoz többet, mint az alapvető minőség rontása."],
        ["Érdemes olcsóbb műszaki csomagot választani?", "Csak tételes összehasonlítás után. Meg kell nézni, mi változik a tartósságban, komfortban, üzemeltetésben, karbantartásban és későbbi bővíthetőségben."],
        ["Miért kerülhet többe egy módosított típusterv?", "A változtatás új tervezést, szakági egyeztetést, eltérő mennyiséget, gyártási vagy kivitelezési módosítást okozhat. A típusterv előnye akkor a legerősebb, ha kevés változtatással használható."],
        ["A berendezés része a teljes projektkeretnek?", "A család saját pénzügyi tervében igen. A kivitelezési ajánlatban viszont csak akkor, ha a tételes tartalom kifejezetten felsorolja. A két nézőpontot nem szabad összekeverni."],
        ["Hogyan kezeljük a jelenlegi otthon eladásából várható összeget?", "Óvatos időzítéssel és reális nettó bevétellel. Vegyétek figyelembe az értékesítés költségeit, a birtokbaadás időpontját, az átmeneti lakhatást és az esetleges áralkut."],
        ["Mi történik, ha menet közben drágább megoldást választunk?", "A változtatás ár-, idő- és műszaki hatását írásban kell látni, mielőtt döntötök. Így nem apró, elszigetelt felárakból áll össze észrevétlenül egy nagy túllépés."],
        ["Mikor kérjünk előzetes hitelbírálatot?", "Még a végleges házválasztás előtt hasznos lehet, hogy a pénzügyi lehetőség ne csak feltételezés legyen. A konkrét folyamatot és érvényességet a választott finanszírozóval kell egyeztetni."],
        ["Számolhatunk állami támogatással biztos bevételként?", "Csak akkor, ha a jogosultságot, feltételeket, határidőt és az építési folyamattal való összhangot illetékes szakember ellenőrizte. A szabályok változhatnak."],
        ["Miért fontos a fizetési ütemezés?", "Mert nem elég, hogy összesen megvan a pénz. Annak akkor kell rendelkezésre állnia, amikor az adott szakasz esedékes, és össze kell hangolni a saját forrást, folyósítást és igazolt készültséget."],
        ["Mit kérdezzünk egy kivitelezési ajánlat áráról?", "Milyen terv és dátum alapján készült, mely készültségi szintet tartalmazza, mi nincs benne, milyen telekfeltételezéssel számol, meddig érvényes, és hogyan kezelik a változásokat."],
        ["A kedvező négyzetméterár mindig jó ajánlat?", "Nem. Eltérhet a számítás alapja, a bruttó és nettó terület, a készültség, a műszaki minőség és a kizárt tételek köre. Csak azonos tartalmat lehet felelősen összehasonlítani."],
        ["Hogyan tervezzük az átmeneti lakhatást?", "Készítsetek külön idő- és költségsort bérleti díjjal, költözésekkel, tárolással és időbeli tartalékkal. Ez gyakran hiányzik a házra fókuszáló kalkulációból."],
        ["Mi legyen, ha a keret és a kívánt méret nem találkozik?", "Először a napi élethez szükséges funkciókat védjétek, majd vizsgáljátok meg a kompaktabb alaprajzot, az ütemezett fejlesztést, a másik telket vagy a későbbre hagyható elemeket."],
        ["Mikor rögzíthető egy ár?", "Ha a terv, a műszaki tartalom, a helyszíni feltételek, a kizárások és az ütemezés meghatározott. A rögzítés jogi feltételeit mindig az adott ajánlat és szerződés tartalmazza."],
        ["Milyen költséget okozhat a rossz talaj?", "Az alapozási mód, földmunka, víztelenítés vagy talajcsere változhat. Pontos hatás csak megfelelő vizsgálat és tervezés alapján állapítható meg."],
        ["Érdemes előre árat kérni a későbbi extrákra?", "Igen, a valószínű opciók nagyságrendjét érdemes látni. A döntést azonban csak pontos specifikáció alapján lehet összehasonlítható és vállalható árral lezárni."],
        ["Miért kell a fenntartási költséget is nézni?", "Mert az otthon pénzügyi hatása a beköltözés után folytatódik. A méret, hőtechnika, gépészet, használati szokás és karbantartás együtt alakítja a havi terhet."],
        ["Hogyan ellenőrizzük, hogy nem felejtettünk ki tételt?", "Használjatok szakaszos ellenőrzőlistát: telek és jogi előkészítés, tervezés, közmű, ház, külső munkák, finanszírozás, átmeneti lakhatás, költözés és tartalék."],
        ["Mi a kalkuláció jó végpontja?", "Egy döntési lap, amely külön mutatja a rögzített, becsült és még vizsgálandó tételeket, a fizetési időpontokat, a tartalékot és azt, mely adat nélkül nem kérhető végleges ajánlat."]
      ])
    ],

    "/igy-lesz-egyszeru": [
      section("EGY FELELŐS, LÁTHATÓ KÖVETKEZŐ LÉPÉS", [
        "Az egyszerűbb építkezés nem attól lesz egyszerű, hogy kevés szó esik a nehéz kérdésekről. Attól, hogy minden döntésnek van gazdája, bemenete és lezárási pontja. Tudjátok, mit kell most megadnotok, milyen szakember dolgozik rajta, milyen dokumentum születik belőle, és mi az a feltétel, amely után tovább lehet lépni.",
        "A folyamatban külön kezeljük a családi döntést, a mérnöki vizsgálatot, a hatósági vagy szolgáltatói ügyet, a pénzügyi feltételt és a kivitelezési feladatot. Így nem marad egy homályos „majd intézik” mondat mögött olyan teendő, amely valójában a ti jóváhagyásotokra vagy hiányzó dokumentumra vár.",
        "A cél nem az, hogy naponta az építkezést irányítsátok. A cél az, hogy a fontos pontokon érthető információból dönthessetek, a döntés következménye pedig visszakereshető legyen."
      ]),
      faqSection("HOGYAN MARAD KÖVETHETŐ A TELJES ÚT?", [
        ["Ki mondja meg, mi a következő feladatunk?", "Minden lezárt szakasz végén meg kell nevezni a következő döntést, a szükséges dokumentumot, a felelőst és a kívánt időpontot. Nem általános teendőlista, hanem konkrét átadás készül."],
        ["Hogyan tudjuk, hogy egy döntés valóban lezárult?", "Írásos összefoglaló rögzíti a választott megoldást, az elfogadott feltételeket, az esetleges nyitott pontokat és azt, hogy mire épülhet a következő lépés."],
        ["Mi történik, ha késünk egy családi döntéssel?", "Meg kell mutatni, mely további feladatokat érinti, és van-e még mozgástér. A hatást nem büntető mondattal, hanem idő- és költségkövetkezménnyel kell láthatóvá tenni."],
        ["Hogyan kérdezhetünk rá egy műszaki részletre?", "A kérdést a kapcsolódó tervhez, helyiséghez vagy tételhez érdemes kötni. Így a válasz nem vész el általános levelezésben, és később is visszakereshető marad."],
        ["Kapunk rendszeres állapotjelentést?", "A konkrét gyakoriságot a szerződés és a projektfolyamat rögzíti. A jó jelentés röviden mutatja a kész állapotot, a következő időszakot, a döntést igénylő pontokat és az eltéréseket."],
        ["Miért kell ennyi mindent írásban rögzíteni?", "Mert hónapok alatt sok részlet változhat, több szakember dolgozik egymás után, és az emlékezet nem közös adatbázis. Az írásos nyom védi a családot és a kivitelezés rendjét."],
        ["Kell minden szakemberrel külön egyeztetnünk?", "A feladatmegosztás célja éppen az, hogy ne nektek kelljen összehangolni a szakágakat. A jóváhagyást igénylő választásokról viszont közvetlen, érthető tájékoztatást kell kapnotok."],
        ["Hogyan kezelik a tervmódosítást?", "Előbb pontosan leírják a kérést, majd megvizsgálják a műszaki, hatósági, ár- és időhatását. Kivitelezési változás csak a szükséges jóváhagyások után indulhat."],
        ["Mi történik egy váratlan helyszíni körülménnyel?", "Dokumentálni kell, meg kell állapítani a döntéshez szükséges szakmai információt, és be kell mutatni a lehetséges megoldások következményeit. Nem maradhat szóbeli rögtönzés."],
        ["Mikor látjuk először a teljes folyamatot?", "Már az előkészítéskor szükség van egy áttekintő ütemre a fő szakaszokkal és függőségekkel. A részletes terv az adatok tisztulásával válik vállalhatóvá."],
        ["Miért nem lehet rögtön kivitelezési kezdőnapot mondani?", "Mert a kezdéshez terv, jogosultság, szerződés, finanszírozás, munkaterület és kapacitás kell. A felelős dátum ezek ellenőrzött rendelkezésre állására épül."],
        ["Hogyan követhető a költség a folyamatban?", "Az alapkerethez képest minden jóváhagyott változást, várható tételt és teljesítést ugyanabban a logikában kell vezetni. Így nem csak a már kifizetett összeg látszik."],
        ["Mi történik, ha egy beszállítás késik?", "A projektvezetés feladata feltárni az érintett munkákat, az alternatívát és az időhatást. Anyagcsere csak műszaki megfelelőség és megrendelői jóváhagyás mellett történhet."],
        ["Mikor választhatunk burkolatot és színeket?", "A választási naptár megmutatja, mikor kell egy döntést lezárni ahhoz, hogy a beszerzés ne tartsa fel a munkát. A túl korai és a túl késői választás egyaránt kerülhető."],
        ["Látogathatjuk az építkezést?", "A biztonságos és szervezett látogatás rendjét a projekt szabályai határozzák meg. A cél, hogy érdemi állapotot lássatok anélkül, hogy a munkavédelmet vagy a munkafolyamatot zavarná."],
        ["Ki ellenőrzi az elkészült munkát?", "Az ellenőrzési rendet a szerződés, a felelős műszaki szerepkörök és a minőségbiztosítás határozza meg. Egyes pontokon dokumentált kapu nélkül nem indulhat a következő munkafázis."],
        ["Mi történik, ha nem értjük a kapott dokumentumot?", "Kérjetek hétköznapi összefoglalót: mit jelent, milyen döntést kér, mi változik, és mi történik, ha nem döntötök. A szakmai pontosság nem indok a ködös kommunikációra."],
        ["Hogyan készülünk az átadásra?", "Már előtte össze kell gyűjteni a dokumentumokat, kezelési tudnivalókat, próbákat és nyitott tételeket. Az átadás nem egyetlen kulcsmozdulat, hanem ellenőrzött lezárás."],
        ["Mi lesz a kérdéseinkkel a beköltözés után?", "Az átadáskor egyértelmű csatorna és bejelentési rend szükséges. A jelzést azonosítani, besorolni, vizsgálni és lezárni kell, visszajelzéssel együtt."],
        ["Miért különül el a döntés és a jóváhagyás?", "Mert előbb meg kell érteni a lehetőségeket és következményeket, utána lehet felelősen engedélyt adni. A sürgetett, információ nélküli igen nem valódi jóváhagyás."],
        ["Milyen dokumentumokat érdemes saját példányban megőriznünk?", "A szerződést és mellékleteit, jóváhagyott terveket, műszaki tartalmat, változásokat, teljesítési és átadási iratokat, kezelési útmutatókat, garanciális adatokat és fontos levelezést."],
        ["Mi történik, ha közben változik az élethelyzetünk?", "Minél előbb jelezzétek. A folyamat megvizsgálja, mi módosítható még ésszerűen, milyen hatással jár, és mi az, amit a projekt biztonsága érdekében már nem célszerű megváltoztatni."],
        ["Hogyan marad rövid és érthető a sok információ?", "Rétegezett kommunikációval: egy rövid döntési összefoglaló, mögötte a tételes szakmai dokumentum, valamint egyértelmű hivatkozás arra, melyik verzió az érvényes."],
        ["Mikor érdemes személyes egyeztetést kérni?", "Ha több szakágat érintő döntésről, jelentős ár- vagy időhatásról, alaprajzi változásról vagy nehezen leírható élethelyzeti igényről van szó."],
        ["Mitől lesz valóban egyszerűbb az építkezés?", "Attól, hogy kevesebb a gazdátlan kérdés, nincs rejtett következő lépés, a döntések időben megszületnek, a változások dokumentáltak, és mindig tudjátok, mi történik most."]
      ])
    ],

    "/kozelrol": [
      section("NEM DÍSZLETET NÉZTEK, HANEM VALÓDI DÖNTÉSI BIZONYÍTÉKOT", [
        "Egy elkészült otthon akkor segít, ha tudjátok, mit kerestek benne. Mekkora valójában a nappali a bútorokkal? Hová kerülnek a kabátok és cipők? Milyen a fény egy borús napon? Hallatszik-e a közös tér a hálóban? Hogyan jut ki a család a kertbe? Ezek a részletek többet mondanak egy élethelyzethez való illeszkedésről, mint egy gondosan beállított fotó.",
        "Folyamatban lévő építkezésen más bizonyítékok fontosak. A szervezettség, az anyagok védelme, a csomópontok kialakítása, a dokumentálás és az egymásra épülő munkák rendje. Amit éppen eltakarás előtt lehet megnézni, azt később már csak fénykép, mérés vagy jegyzőkönyv igazolhatja.",
        "Családi történetet csak valós, hozzájárulással közölhető forrásból mutatunk be. Nem írunk kitalált idézetet, és nem állítunk olyan eredményt, amelynek nincs ellenőrizhető háttere. A hitelesség itt nem hangulat, hanem forrás és kontextus."
      ]),
      faqSection("HOGYAN ÉRDEMES MEGNÉZNI EGY HÁZAT VAGY ÉPÍTKEZÉST?", [
        ["Mit vigyünk magunkkal egy házlátogatásra?", "A saját alaprajzi kérdéseiteket, mérőszalagot, jegyzetet és a valódi bútorok fő méreteit. Fotózni csak előzetes engedéllyel szabad."],
        ["Miért jó ugyanazt a helyiséget több nézőpontból látni?", "Mert a fotó könnyen elrejti a közlekedési útvonalat, a nyíló ajtót vagy a bútorok valós helyigényét. A tér használata mozgás közben derül ki."],
        ["Mire figyeljünk a bejáratnál?", "Van-e esőtől védett érkezés, lerakóhely, cipő- és kabáttárolás, jó út a konyhához, valamint elég hely ahhoz, hogy többen egyszerre érkezzenek."],
        ["Mit nézzünk meg a konyhában?", "A munkafelület folytonosságát, a hűtő és kamra elérését, a főzés útvonalát, az étkező kapcsolatát és azt, hogy nyitott ajtóknál is lehet-e kényelmesen közlekedni."],
        ["Hogyan ellenőrizzük a nappali valós méretét?", "Ne az üres padlót nézzétek. Mérjétek fel a kanapé, asztal, közlekedés, ajtónyitás és a kertkapcsolat helyét együtt."],
        ["Miért fontos a tárolók belsejét is látni?", "Mert a névleges tároló csak akkor hasznos, ha megfelelő mély, elérhető, és a benne tartott tárgy útvonalához közel helyezkedik el."],
        ["Mire figyeljünk a fürdőben?", "A használati sorrendre, a törölköző és tisztálkodószerek helyére, a szellőzésre, a víz útjára, valamint arra, elfér-e segítség, ha kisgyerek vagy idősebb családtag használja."],
        ["Mit árul el egy folyamatban lévő építkezés rendje?", "Önmagában nem bizonyít mindent, de jelzi az anyagvédelem, a munkaterületi biztonság, a hulladékkezelés és a szakágak összehangolásának kultúráját."],
        ["Megnézhetünk eltakarás előtti szerkezeteket?", "Ha a projekt és a munkavédelmi feltételek engedik. Ilyenkor érdemes szakembertől megkérdezni, mely csomópont mit teljesít és hogyan dokumentálják az ellenőrzést."],
        ["Milyen kérdést tegyünk fel egy ott lakó családnak?", "A hétköznapi használatról kérdezzetek: mi működik jól reggel, mit alakítanának másként, mely tér lett fontosabb a vártnál, és hogyan élték meg a döntési folyamatot."],
        ["Honnan tudjuk, hogy egy történet hiteles?", "Azonosítható projekthez, dátumhoz és engedélyezett forráshoz kapcsolódik, világos a szerkesztés módja, és az állítások nem lépik túl azt, amit a forrás valóban elmond."],
        ["Miért nem közölhető minden ügyfél neve és címe?", "A magánélet, a vagyonbiztonság és az adatkezelési hozzájárulás elsődleges. Referencia csak a tulajdonos által engedélyezett részletességgel mutatható be."],
        ["Lehet egy referenciából árat következtetni?", "Nem megbízhatóan. Más lehetett a dátum, telek, műszaki tartalom, módosítás és piaci helyzet. Aktuális árhoz aktuális, tételes ajánlat szükséges."],
        ["Lehet egy referenciából építési időt ígérni?", "Nem. A bemutatott időszak csak az adott projekt dokumentált körülményeivel együtt értelmezhető, és nem automatikus vállalás másik telekre vagy időpontra."],
        ["Mit nézzünk meg a nyílászáróknál?", "A használatot, csatlakozásokat, árnyékolás lehetőségét, küszöböt, vízelvezetést és azt, hogyan kapcsolódik az ablak a bútorozáshoz és a természetes fényhez."],
        ["Hogyan értékeljük a ház akusztikáját?", "Próbáljatok ki hétköznapi helyzetet: beszéd a nappaliban, csukott hálóajtó, gépészeti hang. Egy rövid látogatás nem teljes mérés, de segít jó kérdést feltenni."],
        ["Mire figyeljünk a terasznál?", "A napsütés és árnyék idejére, a szélre, a belső tér kapcsolatára, a bútorozhatóságra, a vízelvezetésre és a kert felé vezető útvonalra."],
        ["Érdemes esős időben is házat nézni?", "Igen, más jelenségek láthatók: a bejárat védelme, a csapadék útja, a természetes fény és a külső közlekedés használhatósága."],
        ["Mit kérdezzünk a karbantartásról?", "Mely felületek igényelnek rendszeres gondozást, hogyan érhetők el a gépészeti elemek, milyen dokumentumot adtak át, és milyen tapasztalat volt az első üzemeltetési időszakban."],
        ["Miért hasznos több, eltérő korú házat megnézni?", "Az új ház a friss kivitelezési részleteket, a régebb óta használt otthon pedig a mindennapi működést és a karbantartási tapasztalatot mutathatja meg."],
        ["Mikor ne menjünk ki egy építkezésre?", "Engedély nélkül, veszélyes munkafázisban, rossz időjárási vagy munkavédelmi körülmények között. A látogatást mindig előre, felelős kísérővel kell egyeztetni."],
        ["Hogyan készítsünk összehasonlítható jegyzetet?", "Minden helyszínen ugyanazt a tíz szempontot értékeljétek: érkezés, közös tér, tárolás, fény, csend, kert, fürdő, gépészet, kivitelezési részlet és saját érzés."],
        ["Miért nem elég egy látványterv?", "A látványterv hangulatot és tervezett megjelenést mutat. Nem helyettesíti a méretellenőrzést, a műszaki dokumentációt, a helyszíni tapasztalatot vagy a teljesített állapot igazolását."],
        ["Mi legyen a látogatás utáni következő lépés?", "Írjátok le külön, mi tetszett, mi kérdéses és mi nem illik hozzátok. Ezután a saját telek és keret adataival beszéljétek át, mely tanulság vihető tovább."],
        ["Mitől lesz egy referencia valódi segítség?", "Ha nem csak szép képet mutat, hanem megnevezi a döntési helyzetet, az ellenőrizhető műszaki vagy használati tanulságot, a forrását és az érvényességi határát."]
      ])
    ],

    "/elso-lepesek": [
      faqSection("HOGYAN HASZNÁLJÁTOK A TUDÁSTÁRAT?", [
        ["Melyik cikkel kezdjünk?", "Azzal, amelyik a következő visszafordítható döntéseteket segíti. Telek előtt telekellenőrzés, házválasztás előtt térigény, ajánlat előtt teljes költség és műszaki tartalom."],
        ["Miért élethelyzet szerint is rendezhető a tudás?", "Mert más kérdés sürgős annak, aki még telket keres, annak, aki tervet hasonlít össze, és annak, aki már finanszírozást szervez."],
        ["Egy cikk alapján meghozható műszaki döntés?", "Nem. A cikk segít megérteni a szempontokat és felkészülni a szakmai egyeztetésre, de a konkrét telek és terv vizsgálatát nem helyettesíti."],
        ["Hogyan ellenőrizzük, hogy egy információ még aktuális?", "Nézzétek meg a dátumot, a hivatkozott szabályt vagy termékadatot, és kérdezzetek rá, változott-e azóta a műszaki, jogi vagy pénzügyi környezet."],
        ["Mit tegyünk, ha két cikk mást mond?", "Vizsgáljátok meg, ugyanarra a helyzetre, készültségi szintre és időpontra vonatkozik-e. Ha a különbség megmarad, konkrét adatokkal kérjetek szakmai állásfoglalást."],
        ["Miért vannak számolók a tudástár mellett?", "A szöveg segít érteni az összefüggést, a számoló pedig a saját adataitokkal láthatóvá teszi a nagyságrendet. Egyik sem végleges ajánlat."],
        ["Elmenthetjük a fontos cikkeket?", "A személyes mentés a későbbi ügyfélfiókban lesz elérhető; addig a cikk címét vagy hivatkozását érdemes közös jegyzetben megőrizni."],
        ["Milyen forrást tekintsetek elsődlegesnek jogi kérdésben?", "Az aktuális jogszabályt, hatósági vagy szolgáltatói tájékoztatást és a konkrét ügyre adott szakértői választ. A közérthető cikk csak eligazít."],
        ["Hogyan használjuk az ellenőrzőlistákat?", "Ne kipipálási versenyként. Minden pontnál írjátok mellé, mi a forrás, ki felel érte, mi hiányzik, és milyen döntést blokkol a hiány."],
        ["Miért fontos külön jegyezni a feltételezéseket?", "Mert a becslés könnyen tényként marad a projektben. Ha megjelölitek, mi csak feltételezés, időben be lehet szerezni a valódi adatot."],
        ["Mikor válik egy kérdés sürgőssé?", "Amikor a válasz hiánya telekvásárlást, tervlezárást, szerződést, rendelést vagy kivitelezési szakaszt érint. A tudástár sorrendet is ad a kérdéseknek."],
        ["Miért érdemes a párunkkal külön is kitölteni egy listát?", "Így láthatóvá válik, hol egyeztek és hol vannak eltérő prioritások. A különbséget olcsóbb a terv előtt rendezni, mint a kivitelezés alatt."],
        ["Hogyan készüljünk telekbejárásra?", "Vigyetek térképet, szabályozási információt, fotózzátok a megközelítést és környezetet, figyeljétek a szintkülönbséget, közműnyomokat, vizet, benapozást és szomszédos épületeket."],
        ["Mikor kérjünk talajvizsgálatot?", "A szükséges vizsgálatot a tervező és szakági szakember határozza meg a helyszín, épület és kockázat alapján. Ezt nem érdemes általános internetes tanácsból eldönteni."],
        ["Mit írjunk fel egy ajánlat olvasásakor?", "A tervverziót, dátumot, készültségi szintet, benne foglalt és kizárt tételeket, telekfeltételezést, érvényességet, fizetési rendet és a változáskezelést."],
        ["Hogyan tanuljunk a műszaki rétegrendekről?", "Előbb a rétegek feladatát értsétek meg: teherhordás, hő, nedvesség, légzárás, hang és felület. Utána hasonlítsatok konkrét, teljes szerkezeteket."],
        ["Miért nem jó csak egyetlen négyzetméterárból kiindulni?", "Mert nem mutatja a telekhatást, a készültséget, a műszaki minőséget, a gépészetet, a tervezést és a kizárásokat. A teljes projekt szerkezetét kell látni."],
        ["Mikor érdemes finanszírozási szakemberrel beszélni?", "Még a ház végleges kiválasztása előtt, különösen ha támogatás, hitel, meglévő ingatlan eladása vagy szakaszos folyósítás kapcsolódik a projekthez."],
        ["Hogyan használjuk a technológia-összehasonlítót?", "Előbb írjátok le a teljesítményelvárást és projektfeltételeket, majd ugyanazok szerint hasonlítsátok össze a dokumentált rendszereket. Ne anyagnevekből válasszatok."],
        ["Mit jelent a forrásdátum egy szakmai cikkben?", "Megmutatja, mikor ellenőrizték az adatokat. Jog, támogatás, ár, termék és szabvány esetén a dátum különösen fontos, mert a tartalom változhat."],
        ["Küldhetünk be saját kérdést?", "Igen, a kapcsolat oldalon írjátok le a konkrét élethelyzetet és azt, mely döntéshez kell válasz. Személyes vagy érzékeny adatot csak a szükséges mértékben adjatok meg."],
        ["Mitől jó egy szakértői válasz?", "Megnevezi, milyen adatokból indul ki, mi a biztos állítás, mi a feltétel, milyen alternatívák vannak, és mely ponton szükséges további vizsgálat."],
        ["Miért találunk előnyöket és hátrányokat is?", "Mert nincs minden telekre, keretre és élethelyzetre automatikusan legjobb megoldás. A felelős tájékoztatás a következményeket is megmutatja."],
        ["Hogyan kerüljük el az információs túlterhelést?", "Egyszerre egy döntési témát válasszatok, írjatok belőle három következtetést és egy nyitott kérdést, majd csak ezután lépjetek a következő területre."],
        ["Mi a tudástár jó eredménye?", "Az, hogy pontosabban kérdeztek, felismeritek a hiányzó adatot, összehasonlítható ajánlatot kértek, és nem kell pusztán hangzatos ígéretekre építenetek."]
      ])
    ],

    "/a-fontos-kerdesek": [
      section("A VÁLASZ AKKOR HASZNOS, HA A TI HELYZETETEKRE VONATKOZIK", [
        "Az építkezés legtöbb félreértése nem abból születik, hogy senki nem válaszolt, hanem abból, hogy egy általános válasz konkrét ígéretnek tűnt. Ezért minden lényeges kérdésnél nézzétek meg, milyen tervre, telekre, műszaki tartalomra, időpontra és dokumentumra vonatkozik a mondat.",
        "Egy jó válasz különválasztja a biztos adatot, a becslést és a még vizsgálandó feltételt. Ha valamelyik hiányzik, nem gyengeség kimondani, hogy további adat kell. Sokkal veszélyesebb egy korai, határozott szám, amely később nem tartható.",
        "A kérdések nem akadályozzák a haladást. A megfelelő pillanatban feltett kérdés megvédi a következő döntést. A cél ezért nem az, hogy minél gyorsabban mindenre igent mondjunk, hanem hogy a fontos igenek mögött ellenőrizhető tartalom legyen."
      ]),
      section("ÖT VÁLASZTÍPUS, AMELYET ÉRDEMES MEGKÜLÖNBÖZTETNI", [
        "Tájékoztató válasz: segít megérteni az általános összefüggést, de nem vállalás. Helyszíni válasz: a telek vagy meglévő épület vizsgálatára épül. Tervezői válasz: jóváhagyott terven és számításon alapul. Pénzügyi válasz: az aktuális jogosultságot és finanszírozói feltételeket vizsgálja. Szerződéses válasz: a felek által elfogadott dokumentumban szereplő konkrét jogot vagy kötelezettséget mutatja.",
        "Ugyanarra a hétköznapi kérdésre több szinten is lehet válaszolni. A „mennyi idő?” kérdésre például adható általános folyamatsorrend, előzetes projektbecslés és szerződéses határidő. Ezek nem felcserélhetők. Mindig kérdezzetek rá, melyik szintről van szó."
      ]),
      faqSection("TOVÁBBI KÉRDÉSEK A FELELŐS DÖNTÉSHEZ", [
        ["Mikor tekinthető egy ár valóban összehasonlíthatónak?", "Ha ugyanarra a tervverzióra, készültségi szintre, műszaki tartalomra, telekfeltételezésre és időpontra vonatkozik, továbbá az eltérő kizárások és opciók külön látszanak."],
        ["Mit jelent az, hogy egy adat még vizsgálandó?", "Azt, hogy a kérdés ismert, de a felelős válaszhoz hiányzik például helyszíni mérés, terv, szolgáltatói információ vagy szakági számítás. Ilyenkor becslést lehet adni, vállalást nem."],
        ["Miért változhat a ház telekre illesztése?", "Az építési hely, tájolás, terepszint, közmű, megközelítés, szomszédos környezet és helyi szabályok együtt határozzák meg, hogyan helyezhető el felelősen az épület."],
        ["Mikor kérjünk második szakvéleményt?", "Ha jelentős kockázatú, visszafordíthatatlan vagy több milliós következményű döntés alapja nem egyértelmű, a dokumentumok ellentmondanak, vagy az indoklás nem ellenőrizhető."],
        ["Hogyan kérdezzünk rá egy garanciára?", "Pontosan: mire terjed ki, mennyi ideig, milyen feltételekkel, ki jogosult bejelenteni, milyen határidő és eljárás vonatkozik rá, valamint mi számít kizárásnak."],
        ["Mit kell tudnunk a készültségi szintekről?", "Az elnevezés önmagában nem elég. Tételesen meg kell nézni a szerkezetet, felületeket, gépészetet, szerelvényeket, külső munkákat, tervezést és minden kizárt elemet."],
        ["Miért nem válaszolható meg általánosan, melyik technológia a legjobb?", "Mert a telek, terv, teljesítménycél, kivitelezési rend, beszállítói rendszer, költség és személyes prioritás együtt dönt. Konkrét rendszereket, nem címkéket kell összevetni."],
        ["Mikor jelent kockázatot egy túl rövid ajánlat?", "Ha nem azonosítja a tervet, a műszaki tartalmat, a mennyiségek alapját, a kizárásokat, a helyszíni feltételeket és a változás kezelését. A rövidség nem lehet a lényegi tartalom hiánya."],
        ["Hogyan kérdezzünk az építési időről?", "Kérjétek a kezdő és záró feltételeket, a fő szakaszokat, a megrendelői döntések határidejét, az ismert külső függőségeket, a tartalékot és a szerződéses következményeket."],
        ["Miért fontos a tervverzió száma vagy dátuma?", "Mert eltérő alaprajzból és műszaki változatból eltérő ár, mennyiség és kivitelezési feladat következik. Verzió nélkül később nem bizonyítható, mire szólt a válasz."],
        ["Mit tegyünk, ha szóban kapunk fontos ígéretet?", "Kérjétek írásos megerősítését, pontos feltételekkel és a kapcsolódó dokumentum megnevezésével. A lényeges vállalásnak a szerződéses rendszerben is helye van."],
        ["Mikor kell bevonni pénzügyi szakembert?", "Mielőtt a támogatást, hitelt vagy ingatlaneladásból származó bevételt biztos forrásként beépítitek a projektbe, illetve a fizetési ütem elfogadása előtt."],
        ["Mit jelent a kulcsrakész állapot?", "Csak a konkrét, tételes műszaki tartalom mondja meg. A piacon az elnevezés eltérően használható, ezért helyiségenként és szakáganként kell ellenőrizni, mi készül el."],
        ["Hogyan ellenőrizzük a szerződés mellékleteit?", "Nézzétek meg, minden hivatkozott terv, műszaki leírás, ütemezés, árlista és eljárás csatolva van-e, azonosítható-e a verziója, és nincs-e ellentmondás a főszöveggel."],
        ["Milyen kérdést tegyünk fel az átadás előtt?", "Mely próbák, dokumentumok, kezelési útmutatók, mérési jegyzőkönyvek, garanciális adatok és nyitott hibák szükségesek ahhoz, hogy az átadás valóban ellenőrzött legyen."],
        ["Miért fontos megkérdezni, mi nincs az árban?", "Mert a hiányzó tétel ettől még szükséges lehet a beköltözéshez vagy a telek használatához. A kizárásokból külön projektköltséget és felelősséget kell képezni."],
        ["Hogyan kezeljük a bizonytalan közműadatot?", "Ne feltételezzétek automatikusan a kapacitást vagy csatlakozási pontot. Szerezzetek szolgáltatói vagy tervezői információt, és addig külön kockázati tételként kezeljétek."],
        ["Mitől lesz egy változtatási kérés biztonságos?", "Pontosan leírt tartalom, tervi jelölés, ár- és időhatás, műszaki ellenőrzés, jóváhagyási határidő és írásos lezárás szükséges hozzá."],
        ["Mikor nem érdemes tovább alkudni egy műszaki tételen?", "Ha a csökkentés tartósságot, biztonságot, jogszabályi megfelelést, későbbi javíthatóságot vagy a szerkezet egészének teljesítményét veszélyezteti. Előbb a felesleges funkciót vizsgáljátok."],
        ["Hogyan derül ki, ki felel egy feladatért?", "A szerződés, szerepkörlista és projektfolyamat együttesen mutassa meg, ki készíti elő, ki ellenőrzi, ki hagyja jóvá és ki végzi el. A többes számú „intézzük” önmagában kevés."],
        ["Mi a teendő, ha egy határidő feltétele nem teljesül?", "Azonnal láthatóvá kell tenni az okot, az érintett következő szakaszokat, a lehetséges korrekciót és az új döntési pontot. A csendben csúszó terv nem kezelési módszer."],
        ["Mikor kérhetünk végleges ajánlatot?", "Ha a szükséges terv, telekadat, készültségi szint, műszaki választás és projektfeltétel rendelkezésre áll. A hiányokat az ajánlat előtt tételesen meg kell nevezni."],
        ["Miért fontos a dokumentumok egységes tárolása?", "Mert a szétszórt levelek és eltérő fájlverziók hibás döntéshez vezethetnek. Minden résztvevőnek azonos, érvényes dokumentumra kell hivatkoznia."],
        ["Hogyan dönthetünk gyorsan anélkül, hogy elhamarkodnánk?", "Előre rögzített döntési szempontokkal, teljes következményképpel és világos határidővel. A gyorsaságot az előkészítés adja, nem az információ elhagyása."],
        ["Mi a jó kérdés ismertetőjele?", "Konkrét döntéshez kapcsolódik, megnevezi a helyzetet és a hiányzó információt, valamint olyan választ kér, amelynek forrása, feltétele és következménye ellenőrizhető."]
      ])
    ],

    "/kezdjuk-egyutt": [
      section("MÁR AZ ELSŐ BESZÉLGETÉSNEK IS LEGYEN EREDMÉNYE", [
        "Nem kell kész tervvel, hibátlan költségvetéssel vagy minden kérdésre adott válasszal érkeznetek. Elég, ha őszintén elmondjátok, hol tartotok, mit szeretnétek megváltoztatni a jelenlegi lakhatásotokban, milyen telek- és pénzügyi adat biztos, és mely döntés okozza most a legnagyobb bizonytalanságot.",
        "A jó első beszélgetés végén nem hangzatos ígéret marad. Kaptok egy rövid, érthető összefoglalót arról, milyen irány látszik reálisnak, milyen dokumentum vagy vizsgálat hiányzik, ki tud válaszolni a nyitott kérdésre, és mi legyen a következő, még biztonságosan megtehető lépés.",
        "Az első beszélgetéshez nem kell hosszú adatlapot kitöltenetek. Elég megírni, hol tartotok, miben kértek segítséget, és hogyan érhetünk el benneteket; a további adatokat csak akkor kérjük, amikor valóban szükség van rájuk."
      ]),
      section("MIT ÉRDEMES ELŐKÉSZÍTENETEK?", [
        "Ha van telketek, legyen kéznél a helyrajzi szám, térképmásolat vagy rendelkezésre álló telekdokumentum. Ha még kerestek, hozzatok két-három példát, és írjátok le, mely térséghez ragaszkodtok. Ha van tervetek, a legfrissebb, azonosítható verziót küldjétek, ne különböző dátumú részleteket.",
        "A pénzügyi keretet nem kell nyilvános vallomásként kezelni. A felelős házajánláshoz viszont tudnunk kell, milyen teljes projektösszeget és havi terhet tartotok vállalhatónak, milyen saját forrás áll rendelkezésre, és mely részletek függenek még ingatlaneladástól vagy finanszírozástól.",
        "Írjatok három rövid mondatot: mitől lenne jobb az új otthonotok; mitől tartotok leginkább az építkezésben; és mi az a feltétel, amelyből nem szeretnétek engedni. Ez a három válasz többet segít, mint egy hosszú, rendezetlen kívánságlista."
      ]),
      faqSection("AZ ELSŐ KAPCSOLATFELVÉTEL GYAKORLATI KÉRDÉSEI", [
        ["Melyik családtagnak érdemes részt vennie az első beszélgetésen?", "Minden olyan döntéshozónak, akinek a pénzügyi keretre, telekre vagy az otthon alapvető használatára érdemi ráhatása van. Így kevesebb lesz a későbbi félreértés."],
        ["Mi történik, ha még nincs pontos pénzügyi keretünk?", "Nagyságrendet és biztonságos havi terhet is megadhattok. A beszélgetés megmutatja, milyen számítást vagy előzetes pénzügyi vizsgálatot érdemes a házválasztás előtt elvégezni."],
        ["Érdemes elküldeni egy internetről mentett alaprajzot?", "Igen, ha inspirációként jelölitek, és leírjátok, mi tetszik benne. Tulajdonjog, megvalósíthatóság és telekillesztés nélkül nem tekinthető kivitelezési tervnek."],
        ["Mit tegyünk, ha csak este tudunk egyeztetni?", "Jelezzétek az elérhető idősávokat. Megnézzük, melyik időpont illeszthető be, és külön visszaigazoljuk a beszélgetést."],
        ["Kérhetünk először csak írásos választ?", "Igen, írjátok le egyetlen, konkrét döntési kérdésként a problémát, és csatoljátok a szükséges adatot. Ha a válasz helyszíni vagy több szakágat érintő vizsgálatot igényel, ezt jelezni fogjuk."],
        ["Milyen fájlokat ne küldjünk el?", "Felesleges személyes okmányt, banki belépési adatot, teljes egészségügyi vagy más érzékeny dokumentumot ne küldjetek. Csak a kérdés megválaszolásához szükséges iratot adjátok át."],
        ["Hogyan jelöljük, ha egy dokumentum már nem aktuális?", "A fájlnévben és az üzenetben is írjátok le, hogy korábbi változat, és nevezzétek meg a jelenleg érvényes dokumentumot. Az eltérő verziókat nem szabad összekeverni."],
        ["Kapunk összefoglalót a beszélgetés után?", "A jó folyamat röviden rögzíti a megismert helyzetet, a tisztázott pontokat, a hiányzó adatokat és a következő lépést. Konkrét tartalma az egyeztetés típusától függ."],
        ["Mi történik, ha kiderül, hogy más szolgáltatásra van szükségünk?", "Ezt egyenesen jelezni kell. Lehet, hogy telekvizsgálat, pénzügyi előkészítés, egyedi tervezés vagy felújítási állapotfelmérés előzi meg a házválasztást."],
        ["Kötelez bennünket valamire az első egyeztetés?", "Nem. Bármilyen későbbi megrendeléshez külön, egyértelmű ajánlat és elfogadás szükséges. A tájékozódó beszélgetés nem szerződéskötés."],
        ["Miért kérdezik meg a kívánt költözési időpontot?", "Az időpont segít visszafelé megtervezni az előkészítést és felismerni, ha a telek, terv vagy finanszírozás miatt a várakozás nem reális. Ettől még nem válik vállalt határidővé."],
        ["Mikor érdemes helyszíni találkozót kérni?", "Ha a telek beépíthetősége, szintkülönbsége, megközelítése, meglévő épület állapota vagy más, fotóból és dokumentumból nem eldönthető körülmény alapvetően befolyásolja az irányt."],
        ["Hogyan válasszuk ki az elsőként átbeszélendő három házat?", "Ne csak külső kép alapján. Válasszatok eltérő méretű vagy szervezésű alaprajzokat, és mindegyikhez írjátok le, miért lehetne jó, illetve mi az egyetlen legnagyobb kétségetek."],
        ["Mi legyen, ha a telek még csak kiszemelt, de nem a miénk?", "Ezt egyértelműen jelezzétek. Vásárlás előtt a rendelkezésre álló jogi, szabályozási, közmű- és helyszíni adatokat kell ellenőrizni; a vizsgálat nem jelent foglalást vagy tulajdonjogot."],
        ["Kaphatunk tájékoztatást több technológiáról is?", "Igen. Ugyanazok szerint a szempontok szerint érdemes összevetni a konkrét rendszereket: teljesítmény, rétegrend, kivitelezési feltétel, karbantartás, árhatár és dokumentáció."],
        ["Mit mondjunk el a korábbi rossz építkezési tapasztalatunkból?", "Azt, mi okozta a bizonytalanságot: hiányzó ár, késői változás, kommunikáció, minőség vagy határidő. Így már az elején látható, milyen bizonyítékra és folyamatra van szükségetek."],
        ["Hogyan készül ajánlat saját tervre?", "Előbb ellenőrizni kell a terv teljességét és verzióját, tisztázni a kívánt készültségi szintet, a telekfeltételeket, a műszaki kérdéseket és a kizárásokat. Hiányos adatból csak előzetes becslés készülhet."],
        ["Miért kérdezik meg, min szeretnénk változtatni?", "Mert a módosítás hatással lehet a tervezésre, árra, időre és a típusterv előnyeire. A korai, pontos kérdés segít eldönteni, módosítás vagy másik terv a jobb út."],
        ["Elindíthatjuk a beszélgetést telek és terv nélkül is?", "Igen. Ilyenkor a cél az élethelyzet, a térigény, a térség és a pénzügyi keret rendezése, valamint annak kijelölése, milyen adatot szerezzetek meg legközelebb."],
        ["Mikor kapunk személyre szabott következő lépést?", "Miután a rendelkezésre álló adatokat áttekintettük, és kiderült, mi a döntést leginkább blokkoló hiány. A következő lépés lehet számítás, dokumentumkérés, helyszíni vizsgálat vagy konzultáció."],
        ["Hogyan kezelik a megadott adatainkat?", "Az adatbekérés előtt könnyen elérhető tájékoztató mutatja be, mire használjuk az adatokat, meddig őrizzük meg őket, ki férhet hozzájuk, és milyen jogaitok vannak."],
        ["Kérhetünk csak házlátogatást?", "Igen, ha van erre engedéllyel és megfelelő körülményekkel rendelkező referencia. A tulajdonos magánélete, a munkavédelem és az időpont-egyeztetés minden esetben elsődleges."],
        ["Miért jobb egyetlen, jól megfogalmazott kérdéssel kezdeni?", "Mert gyorsan megmutatja, milyen adat, szakember vagy döntési folyamat szükséges. A többi kapcsolódó kérdés ezután rendezett sorrendben bontható ki."],
        ["Mit tegyünk, ha az első egyeztetés után még bizonytalanok vagyunk?", "Kérjetek írásos összefoglalót és különítsétek el, mi tény, mi lehetőség és mi vizsgálandó. Ne lépjetek tovább olyan döntésben, amelynek lényegi következménye nem érthető."],
        ["Mi a jó első kapcsolatfelvétel eredménye?", "Nem feltétlenül ajánlat. Jó eredmény a tisztább cél, a reális irány, a szükséges dokumentumok listája és egyetlen világos következő lépés, amelyet mindkét fél ért."]
      ])
    ]
  };
})();
