const DECISION_PAGE_MAP = {
  "/szamolok/havi-teher": {
    id: "EH-HU-302",
    layout: "monthly-room",
    eyebrow: "Havi lehetőségek",
    title: "Mennyi fér bele úgy, hogy közben élni is maradjon pénzetek?",
    intro: "A saját otthon akkor jó döntés, ha a havi kiadások mellett a család megszokott élete is biztonságban marad. Nézzük meg együtt, milyen összeg vállalható nyugodtan.",
    photo: "everyday-monthly-budget-planning-v1.webp",
    primary: ["Kiszámolom a kényelmes havi összeget", "#szamolo"],
    secondary: ["Pénzügyi tanácsadóval beszélnék", "/mi-intezzuk/finanszirozas"],
    body: `
      <section class="monthly-principle" aria-labelledby="monthly-principle-title">
        <div><p class="decision-kicker">Ne a banki maximum legyen a cél</p><h2 id="monthly-principle-title">A törlesztő mellett a családi életnek is maradjon helye.</h2></div>
        <div class="monthly-principle__copy"><p>A hitelképesség és a kényelmesen vállalható havi összeg nem ugyanaz. A számolásból ezért nemcsak az derül ki, mekkora összeg jöhet szóba, hanem az is, mennyi marad a mindennapi kiadásokra, a tartalékra és a váratlan helyzetekre.</p><p>Ti mondjátok meg, melyik havi határ fölé nem szeretnétek menni. Ebből indulunk visszafelé a saját forráshoz és a szóba jöhető otthonokhoz.</p></div>
      </section>
      <section class="monthly-balance" aria-label="A havi költség három része">
        <article><span>01</span><h3>Biztos megélhetés</h3><p>Lakhatás, étkezés, közlekedés és a család rendszeres kiadásai.</p></article>
        <article><span>02</span><h3>Otthonra vállalt összeg</h3><p>Az a havi összeg, amelyet hosszabb távon is nyugodtan ki tudtok fizetni.</p></article>
        <article><span>03</span><h3>Megmaradó mozgástér</h3><p>Megtakarítás, váratlan kiadás és azok a dolgok, amelyekért jó élni.</p></article>
      </section>
      <section id="szamolo" class="decision-tool decision-tool--monthly" data-nim-widget="monthly-affordability" aria-labelledby="monthly-tool-title">
        <div class="decision-tool__intro"><p class="decision-kicker">Számoljuk ki együtt</p><h2 id="monthly-tool-title">Négy adatból már el lehet indulni.</h2><p>A végleges oldalon itt adjátok meg a saját forrást, a háztartás bevételét, a meglévő havi kötelezettségeket és azt az összeget, amelyet kényelmesnek éreztek.</p></div>
        <div class="monthly-inputs" aria-label="A számításhoz szükséges adatok"><span>Saját forrás</span><span>Havi nettó bevétel</span><span>Meglévő terhek</span><span>Vállalható havi összeg</span></div>
        <div class="tool-result"><strong>Nem egy hitelígéretet kaptok.</strong><p>Egy érthető pénzügyi sávot, amelyből tovább lehet lépni a valódi banki egyeztetés és a megfelelő házak felé.</p></div>
      </section>
      <section class="monthly-next"><div><p class="decision-kicker">Ha megvan a havi határ</p><h2>Megmutatjuk, milyen otthonok jöhetnek szóba.</h2></div><ol><li><b>1</b><span>Rögzítjük a saját forrást és a kényelmes havi összeget.</span></li><li><b>2</b><span>Átnézzük a finanszírozás reális lehetőségeit.</span></li><li><b>3</b><span>Azokat a házakat mutatjuk meg, amelyek beleférhetnek.</span></li></ol></section>`,
    faq: [
      ["Ez a számítás megmutatja, mekkora hitelt kapunk?", "Nem. A számolás abban segít, hogy előbb a család számára kényelmes havi határt lássátok. A hitelösszeget és a pontos feltételeket a bank a saját vizsgálata alapján állapítja meg."],
      ["Miért kell megadni a meglévő havi terheket?", "Mert egy autóhitel, személyi kölcsön vagy más rendszeres kötelezettség csökkenti azt az összeget, amelyet az új otthonra biztonsággal vállalhattok."],
      ["A támogatások is bekerülnek a számításba?", "Csak az aktuális, rátok valóban alkalmazható lehetőségek. A jogosultságot és a feltételeket pénzügyi szakemberrel kell ellenőrizni."],
      ["Mi történik a számolás után?", "Kérhettek személyes egyeztetést, ahol a pénzügyi keretet összekapcsoljuk a szóba jöhető házakkal és a teljes építkezési költséggel."]
    ],
    closingTitle: "Legyen saját otthonotok úgy, hogy a hétköznapok is biztonságban maradnak.",
    closingCta: ["Átnézzük a lehetőségeinket", "/mi-intezzuk/finanszirozas"]
  },

  "/szamolok/teljes-projektkeret": {
    id: "EH-HU-303",
    layout: "cost-map",
    eyebrow: "Az építkezés teljes költsége",
    title: "Mennyibe kerül minden együtt, mire beköltöztök?",
    intro: "A ház ára fontos, de önmagában nem elég a döntéshez. Tegyük mellé a telket, az előkészítést, a közműveket, a külső munkákat és a biztonsági tartalékot is.",
    photo: "everyday-total-cost-site-planning-v1.webp",
    primary: ["Összerakom a teljes költséget", "#koltsegterkep"],
    secondary: ["Kérek személyes költségáttekintést", "/kezdjuk-egyutt"],
    body: `
      <section class="cost-opening"><div class="cost-opening__statement"><small>Nem egyetlen árat kerestek.</small><strong>Egy végigvihető építkezést terveztek.</strong></div><p>A jó költségtervben minden nagy tételnek helye van. Így már az elején kiderül, hol van biztos összeg, hol kell becsléssel számolni, és melyik kérdéshez szükséges még telek- vagy tervadat.</p></section>
      <section id="koltsegterkep" class="cost-map-board" data-nim-widget="total-build-cost" aria-labelledby="cost-map-title">
        <header><p class="decision-kicker">A teljes költségtérkép</p><h2 id="cost-map-title">Nyolc terület, amelyet együtt érdemes látni.</h2></header>
        <div class="cost-map-board__grid"><article><b>Telek</b><span>vétel, illeték, rendezés</span></article><article><b>Tervezés</b><span>vizsgálatok és hatósági feladatok</span></article><article><b>Előkészítés</b><span>talaj, alapozás, megközelítés</span></article><article><b>Közművek</b><span>csatlakozások és kapacitások</span></article><article><b>A ház</b><span>rögzített műszaki tartalom</span></article><article><b>Külső munkák</b><span>járda, terasz, kerítés, kert</span></article><article><b>Költözés</b><span>berendezés és induló kiadások</span></article><article><b>Tartalék</b><span>külön kezelt biztonsági összeg</span></article></div>
      </section>
      <section class="cost-certainty"><article class="is-known"><span>Biztos</span><h3>Ami már pontosan meghatározható</h3><p>Kiválasztott terv, rögzített műszaki tartalom és ellenőrzött helyszíni adat alapján.</p></article><article class="is-estimate"><span>Becsült</span><h3>Amihez már van használható tartomány</h3><p>Korai tervezésnél segít helyet hagyni a még nem végleges tételeknek.</p></article><article class="is-open"><span>Vizsgálandó</span><h3>Amihez még hiányzik egy fontos adat</h3><p>Nem rejtjük el egy átlagárban. Megmutatjuk, mit kell tisztázni hozzá.</p></article></section>
      <section class="cost-conversation"><div><p class="decision-kicker">Otthon – egyszerűen.</p><h2>A költségvetés akkor jó, ha dönteni is lehet belőle.</h2></div><div><p>Az összesítés végén nem puszta számoszlopot kaptok. Látszik, melyik tétel kötelező, melyiken lehet változtatni, és mi az, amit nem érdemes a tartalék rovására bevállalni.</p><a class="text-link" href="${href('/kezdjuk-egyutt')}" data-route>Nézzük át együtt a teljes költséget →</a></div></section>`,
    faq: [
      ["Miért nem elég a ház négyzetméterára?", "Mert két azonos méretű ház terve, műszaki tartalma és telke eltérő lehet. A valós költséget a teljes terv, a választott készültség és a helyszíni adottságok együtt adják."],
      ["Mekkora tartalékkal számoljunk?", "A szükséges tartalékot a terv készültsége, a telek ismertsége és a még nyitott döntések alapján kell meghatározni. A számoló nem helyettesíti ezt egyetlen, mindenkire érvényes százalékkal."],
      ["A kert és a kerítés is része a ház árának?", "Csak akkor, ha a kiválasztott műszaki tartalom ezt kifejezetten tartalmazza. A külső munkákat ezért külön soron mutatjuk meg."],
      ["Mikor lesz a becslésből tételes ajánlat?", "Amikor rendelkezésre áll a terv, a helyszín szükséges adatai és a kiválasztott műszaki tartalom. Ekkor lehet a még nyitott tételeket pontosítani."]
    ],
    closingTitle: "Ne csak a ház árát lássátok. Lássátok a beköltözésig vezető teljes költséget.",
    closingCta: ["Kérek költségáttekintést", "/kezdjuk-egyutt"]
  },

  "/szamolok/utemterv": {
    id: "EH-HU-304",
    layout: "schedule-line",
    eyebrow: "Építési ütemterv",
    title: "Mikorra lehet kész az otthonotok?",
    intro: "A beköltözés napja nem a kivitelezés első napján dől el. A telek, a tervek, a döntések és az építési szakaszok együtt adják a reális menetrendet.",
    photo: "everyday-construction-schedule-v1.webp",
    primary: ["Megnézem a várható ütemezést", "#utemvonal"],
    secondary: ["Az indulásról egyeztetnék", "/kezdjuk-egyutt"],
    body: `
      <section id="utemvonal" class="schedule-rail" data-nim-widget="build-schedule" aria-labelledby="schedule-title"><header><p class="decision-kicker">A beköltözéshez vezető út</p><h2 id="schedule-title">Minden szakasznak megvan a feltétele.</h2></header><ol><li><b>01</b><strong>Telek és igények</strong><span>Helyszíni adottságok, házméret, családi szempontok.</span></li><li><b>02</b><strong>Tervezés</strong><span>Alaprajz, szakági tervek, szükséges egyeztetések.</span></li><li><b>03</b><strong>Előkészítés</strong><span>Beszerzés, szervezés, munkaterület és kezdési feltételek.</span></li><li><b>04</b><strong>Kivitelezés</strong><span>Egymásra épülő munkaszakaszok és ellenőrzési pontok.</span></li><li><b>05</b><strong>Átadás</strong><span>Próbák, dokumentumok, hibajegyzék és birtokbaadás.</span></li></ol></section>
      <section class="schedule-risks"><div><p class="decision-kicker">Mi mozdíthatja el a dátumot?</p><h2>Az időt nem ígérettel, hanem előkészítéssel lehet védeni.</h2></div><div class="schedule-risks__items"><article><b>Tervváltozás</b><p>A késői módosítás új számítást, beszerzést vagy munkasorrendet igényelhet.</p></article><article><b>Telekadottság</b><p>Talaj, közmű, megközelítés vagy tereprendezés hatással lehet a kezdésre.</p></article><article><b>Anyagválasztás</b><p>A hosszabb szállítási idejű termékekről korábban kell dönteni.</p></article><article><b>Időjárás</b><p>Bizonyos munkákhoz megfelelő hőmérséklet és száraz környezet szükséges.</p></article></div></section>
      <section class="schedule-calendar"><div class="schedule-calendar__face" aria-hidden="true"><span>TERV</span><span>HELYSZÍN</span><span>DÖNTÉSEK</span><strong>INDULHAT</strong></div><div><p class="decision-kicker">A számoló ezt rendezi össze</p><h2>Nem egy találomra kiválasztott dátumot mutat.</h2><p>A telek és a terv jelenlegi állapotából indul ki. Külön jelzi az előkészítést, az építés fő szakaszait és azt a tartalékot, amelyet az időjárás vagy más, előre látható körülmény miatt érdemes beépíteni.</p><p>A tényleges kezdést és átadást csak a kapacitás, a kész tervek és a szerződés alapján lehet vállalni.</p></div></section>`,
    faq: [
      ["Telek nélkül is készíthető előzetes ütemezés?", "Igen. Ilyenkor a telekválasztás és a helyszíni vizsgálatok külön előkészítő szakaszként jelennek meg. Végleges kezdési időpont csak a kiválasztott telek ellenőrzése után adható."],
      ["Miért számít, mikor választjuk ki a burkolatokat és a gépészetet?", "Mert a gyártási és szállítási idők eltérnek. A korai döntés segít abban, hogy a szükséges termék a megfelelő munkaszakaszra rendelkezésre álljon."],
      ["Az időjárással is számol az ütemezés?", "Ahol az adott munkafázisnál ennek jelentősége van, ott igen. A számítás külön tartalékot hagyhat az évszak és a munka jellegének megfelelően."],
      ["Mikor kapunk vállalt átadási dátumot?", "A jóváhagyott tervek, a helyszíni feltételek, a kiválasztott műszaki tartalom és az elérhető kivitelezési kapacitás rögzítése után, a szerződésben."]
    ],
    closingTitle: "Ha a lépések sorrendben vannak, a költözés napja sem marad találgatás.",
    closingCta: ["Kérek indulási egyeztetést", "/kezdjuk-egyutt"]
  },

  "/szamolok/felujitas-vagy-uj": {
    id: "EH-HU-305",
    layout: "three-choices",
    eyebrow: "Három lehetséges út",
    title: "Felújítás, bővítés vagy új ház?",
    intro: "A legolcsóbbnak látszó megoldás nem mindig kerül a legkevesebbe. Hasonlítsátok össze, mennyi munkát, bizonytalanságot és használati kompromisszumot jelent a három lehetőség.",
    photo: "everyday-renovate-or-new-inspection-v1.webp",
    primary: ["Összehasonlítom a lehetőségeket", "#harom-ut"],
    secondary: ["Kérek helyszíni állapotfelmérést", "/mi-intezzuk/felujitas"],
    body: `
      <section class="choice-question"><p>Megvan a ház, de kevés a hely? Jó a telek, de rossz az elrendezés? A falak állapota bizonytalan? A válasz nem egyetlen négyzetméterárból derül ki.</p><strong>Először az épületet és a család valódi célját kell megérteni.</strong></section>
      <section id="harom-ut" class="choice-board" data-nim-widget="renovate-extend-new" aria-labelledby="choice-title"><header><p class="decision-kicker">Három út ugyanarra a családi célra</p><h2 id="choice-title">Hasonlítsátok össze azonos szempontok alapján.</h2></header><div class="choice-board__columns"><article><span>A</span><h3>Felújítás</h3><p>A meglévő méret marad, a műszaki állapot és a komfort javul.</p><ul><li>feltárási kockázat</li><li>részleges kiköltözés</li><li>meglévő alaprajzi kötöttségek</li></ul></article><article><span>B</span><h3>Bővítés</h3><p>A meglévő ház új helyiségekkel és kapcsolatokkal egészül ki.</p><ul><li>szerkezeti csatlakozás</li><li>engedélyezhetőség</li><li>régi és új részek összehangolása</li></ul></article><article><span>C</span><h3>Új otthon</h3><p>A ház az első vonaltól a család mostani igényeire készül.</p><ul><li>szabadabb alaprajz</li><li>egységes műszaki rendszer</li><li>a teljes építkezés költsége</li></ul></article></div></section>
      <section class="choice-matrix" aria-label="Összehasonlítási szempontok"><div class="choice-matrix__labels"><span>Költség</span><span>Idő</span><span>Bizonytalanság</span><span>Energetika</span><span>Használhatóság</span></div><div class="choice-matrix__message"><p class="decision-kicker">Nincs előre kijelölt győztes</p><h2>A ház állapota dönti el, melyik út éri meg.</h2><p>Állapotfelmérés nélkül a felújítás ára könnyen félrevezető lehet. Új építésnél pedig a telekhez és a teljes költséghez kell ugyanilyen őszintén viszonyulni.</p></div></section>
      <section class="choice-proof"><div><h2>Mit néz meg a mérnök?</h2><p>Az első helyszíni vizsgálat célja, hogy az érzelmi kötődés mellé műszaki tények is kerüljenek.</p></div><ul><li>Tartószerkezet és látható repedések</li><li>Nedvesség, tető és vízelvezetés</li><li>Gépészet és elektromos rendszer</li><li>Hőszigetelés és nyílászárók</li><li>Bővíthetőség és helyi építési szabályok</li></ul></section>`,
    faq: [
      ["Megmondható fényképek alapján, mennyibe kerül a felújítás?", "Fényképekből előzetes kérdéslista készülhet, de konkrét költséghez helyszíni állapotfelmérés és szükség szerint feltárás kell."],
      ["Mikor lehet jobb döntés a bővítés?", "Ha a meglévő épület szerkezetileg megfelelő, az alaprajz jól kapcsolható az új részhez, és a telek szabályai lehetővé teszik a bővítést."],
      ["Az új ház mindig drágább?", "Nem. Nagy mértékű szerkezeti javítás, teljes gépészeti csere és rosszul alakítható alaprajz mellett a felújítás teljes költsége megközelítheti vagy meghaladhatja egy új házét."],
      ["Lakhatunk a házban a felújítás alatt?", "A munkák terjedelmétől függ. Gépészeti, elektromos vagy szerkezeti beavatkozásnál gyakran biztonságosabb és gyorsabb az ideiglenes kiköltözés."]
    ],
    closingTitle: "Ne megszokásból döntsetek a régi ház mellett – és ne divatból az új mellett.",
    closingCta: ["Kérek állapotfelmérést", "/mi-intezzuk/felujitas"]
  },

  "/szamolok/energia-es-koltseg": {
    id: "EH-HU-306",
    layout: "warm-cold",
    eyebrow: "Építési és fenntartási költség",
    title: "Mennyibe kerül megépíteni – és mennyibe kerül majd használni?",
    intro: "A szigetelés, az árnyékolás, a nyílászárók és a gépészet nem különálló tételek. Együtt határozzák meg az otthon kényelmét és a későbbi energiaigényt.",
    photo: "everyday-energy-comfort-winter-v1.webp",
    primary: ["Összehasonlítom a műszaki változatokat", "#energia-osszehasonlitas"],
    secondary: ["Megnézem a technológiákat", "/mibol-epuljon"],
    body: `
      <section class="comfort-opening"><div><p class="decision-kicker">Nem a legdrágább gép a kiindulópont</p><h2>Előbb legyen kisebb az épület energiaigénye.</h2></div><p>A kompakt házforma, a jó tájolás, a hőhidak kezelése, a légtömörség és a nyári árnyékolás csökkentheti azt a teljesítményt, amelyet a fűtési és hűtési rendszernek biztosítania kell.</p></section>
      <section id="energia-osszehasonlitas" class="energy-board" data-nim-widget="energy-cost-comparison" aria-labelledby="energy-title"><header><p class="decision-kicker">Két költséget teszünk egymás mellé</p><h2 id="energy-title">Amit most fizettek ki, és amit évről évre használni fogtok.</h2></header><div class="energy-board__scale"><article><span>ÉPÍTÉSKOR</span><b>Szerkezet és szigetelés</b><b>Nyílászárók</b><b>Árnyékolás</b><b>Gépészet</b></article><div class="energy-board__bridge" aria-hidden="true"><i></i><strong>együtt működő ház</strong><i></i></div><article><span>HASZNÁLAT KÖZBEN</span><b>Fűtés és hűtés</b><b>Meleg víz</b><b>Szellőzés</b><b>Karbantartás</b></article></div></section>
      <section class="comfort-scenes"><article><span>Január</span><h3>Egyenletes meleg</h3><p>Ne csak a levegő hőmérséklete legyen kellemes. A belső felületek hőmérséklete és a huzatérzet is számít.</p></article><article><span>Július</span><h3>Árnyék még a meleg előtt</h3><p>A megfelelő külső árnyékolás kevesebb hőt enged be, mint amennyit később géppel kellene eltávolítani.</p></article><article><span>Egész évben</span><h3>Friss levegő, kezelhető páratartalom</h3><p>A szellőzés módját a ház használatához és légtömörségéhez kell választani.</p></article></section>
      <section class="energy-result"><div class="energy-result__dial" aria-hidden="true"><span>BERUHÁZÁS</span><i></i><span>FENNTARTÁS</span></div><div><p class="decision-kicker">A számolás eredménye</p><h2>Nem egyetlen „legjobb” csomag, hanem összehasonlítható választások.</h2><p>Minden változatnál együtt jelenik meg a várható építési többlet, a számításhoz használt energiaár és a becsült éves fogyasztási tartomány. Így látszik, mi ad valódi komfortot, és melyik fejlesztés térülhet meg a család használati szokásai mellett.</p></div></section>`,
    faq: [
      ["Meg lehet mondani előre a pontos éves rezsit?", "Pontosan nem, mert a fogyasztást az időjárás, a család szokásai és a beállított hőmérséklet is befolyásolja. Összehasonlítható becslési tartomány azonban készíthető azonos feltételekkel."],
      ["Mindig a vastagabb szigetelés a jobb?", "Nem önmagában. A fal, a födém, a padló, a nyílászárók, a hőhidak és a légtömörség együtt határozzák meg a ház viselkedését."],
      ["A hőszivattyú minden házhoz jó választás?", "A hőleadó rendszer, az épület hőigénye, az elektromos kapacitás és a használati mód alapján lehet felelősen dönteni róla."],
      ["Mit kell megadni az összehasonlításhoz?", "Az alapterületet, a fő szerkezeti és szigetelési adatokat, a nyílászárók jellemzőit, a tervezett gépészetet és a család használati szokásait."]
    ],
    closingTitle: "Olyan műszaki tartalmat válasszatok, amelyet nemcsak megépíteni, hanem használni is jó.",
    closingCta: ["Kérek műszaki összehasonlítást", "/mibol-epuljon"]
  },

  "/szamolok/gyors-hazellenorzes": {
    id: "EH-HU-307",
    layout: "family-compass",
    eyebrow: "Házválasztó",
    title: "Melyik ház illik a családotokhoz?",
    intro: "Nem kell végignéznetek minden tervet. Válaszoljatok hét hétköznapi kérdésre, és megmutatjuk azt a néhány házat, amelyet érdemes közelebbről megnéznetek.",
    photo: "everyday-house-fit-studio-v1.webp",
    primary: ["Elindítom a házválasztást", "#het-kerdes"],
    secondary: ["Élethelyzet szerint nézelődöm", "/otthonvalaszto"],
    body: `
      <section class="fit-promise"><div class="fit-promise__number">3</div><div><p class="decision-kicker">Nem száz terv</p><h2>Legfeljebb három ház, világos indoklással.</h2><p>A rövid lista nem mondja meg helyettetek, melyik otthonba szeressetek bele. Abban segít, hogy a család mérete, a telek, a pénzügyi határ és a fontos helyiségek alapján ne vesztegessetek időt olyan tervekre, amelyek eleve nem működnek.</p></div></section>
      <section id="het-kerdes" class="fit-questions" data-nim-widget="house-fit-selector" aria-labelledby="fit-title"><header><p class="decision-kicker">Hét kérdés a saját életetekről</p><h2 id="fit-title">Nem szaknyelven. Úgy, ahogy otthon is megbeszélnétek.</h2></header><div class="fit-questions__grid"><article><b>01</b><span>Hányan költöznétek?</span></article><article><b>02</b><span>Változhat a család létszáma?</span></article><article><b>03</b><span>Van már telketek?</span></article><article><b>04</b><span>Mikor szeretnétek költözni?</span></article><article><b>05</b><span>Mekkora összeget szántok az építkezésre?</span></article><article><b>06</b><span>Melyik helyiségből nem engedtek?</span></article><article><b>07</b><span>Szeretnétek később bővíteni?</span></article></div></section>
      <section class="fit-results"><header><p class="decision-kicker">Mit kaptok a végén?</p><h2>Három különböző okból jó választást.</h2></header><div><article><small>LEGKÖZELEBBI TALÁLAT</small><strong>A családi rutinotokhoz illik</strong><p>Megmutatjuk, mely napi helyzetekben működik jól az alaprajz.</p></article><article><small>ÉSSZERŰ ALTERNATÍVA</small><strong>A keretetekhez áll közelebb</strong><p>Látszik, miben ad kevesebbet, és hol marad teljes értékű otthon.</p></article><article><small>JÖVŐRE TERVEZVE</small><strong>A későbbi változást kezeli jobban</strong><p>Külön jelezzük, ha a bővíthetőség vagy a szobák alakíthatósága erősebb.</p></article></div></section>
      <section class="fit-exclusion"><div><span>!</span><h2>Azt is elmondjuk, miért nem ezt választanánk.</h2></div><p>Minden javasolt háznál megnevezünk egy olyan szempontot, amely miatt másik terv lehet jobb. Így nem reklámszöveget kaptok, hanem használható összehasonlítást.</p></section>`,
    faq: [
      ["A házválasztó automatikusan kiválasztja a végleges tervet?", "Nem. Rövid listát készít, és megmutatja a különbségeket. A végleges döntéshez a telket, a költséget és az alaprajz részleteit is át kell nézni."],
      ["Telek nélkül is használható?", "Igen. Ilyenkor több terv maradhat a listán, és külön megmutatjuk, milyen telekszélességet vagy tájolást érdemes keresni hozzájuk."],
      ["Mi történik, ha egyik ház sem illik pontosan?", "Nem erőltetünk rossz találatot. Megmutatjuk, melyik igény szűkíti leginkább a választást, és hogy módosítás vagy egyedi tervezés lehet-e a következő lépés."],
      ["A találatoknál árat is látunk majd?", "Igen, ha az adott házhoz rendelkezésre áll aktuális, ellenőrzött ár és a hozzá tartozó műszaki tartalom. Hiányzó adatot nem pótolunk becsléssel."]
    ],
    closingTitle: "Kevesebb böngészés. Több idő arra, hogy megtaláljátok a saját otthonotokat.",
    closingCta: ["Megnézem a hozzánk illő házakat", "/otthonvalaszto"]
  }
};

function decisionAction(item, secondary = false) {
  if (!item) return "";
  const localAnchor = item[1].startsWith("#");
  const target = localAnchor ? item[1] : href(item[1]);
  return `<a class="button${secondary ? " button--secondary" : ""}" href="${target}"${localAnchor ? "" : " data-route"}>${escapeHtml(item[0])}</a>`;
}

function decisionFaqMarkup(items) {
  return `<section class="decision-faq" aria-labelledby="decision-faq-title"><div class="decision-faq__heading"><p class="decision-kicker">Gyakori kérdések</p><h2 id="decision-faq-title">Amit még érdemes tisztázni</h2></div><div class="decision-faq__items">${items.map(([question, answer]) => `<details><summary>${escapeHtml(question)}</summary><p>${escapeHtml(answer)}</p></details>`).join("")}</div></section>`;
}

function renderDecisionPage(path) {
  const page = DECISION_PAGE_MAP[path];
  if (!page) return false;
  document.title = `${page.eyebrow} | Everyday Homes staging`;
  const main = document.querySelector("main");
  main.innerHTML = `
    <article class="decision-page decision-page--${escapeHtml(page.layout)}" data-page-id="${escapeHtml(page.id)}" data-release-state="review-required">
      <section class="decision-hero">
        <div class="decision-hero__photo" style="background-image:url('${BASE}/assets/photos/${escapeHtml(page.photo)}')" role="img" aria-label="${escapeHtml(page.eyebrow)} – Everyday Homes"></div>
        <div class="decision-hero__copy"><p class="decision-brandline">Otthon – egyszerűen.</p><p class="eyebrow">${escapeHtml(page.eyebrow)}</p><h1>${escapeHtml(page.title)}</h1><p class="lede">${escapeHtml(page.intro)}</p><div class="actions">${decisionAction(page.primary)}${decisionAction(page.secondary, true)}</div></div>
      </section>
      <nav class="decision-switcher" aria-label="Számolók és választást segítő eszközök">
        ${Object.entries(DECISION_PAGE_MAP).map(([route, item]) => `<a href="${href(route)}" data-route${route === path ? ' aria-current="page"' : ""}>${escapeHtml(item.eyebrow)}</a>`).join("")}
      </nav>
      <div class="decision-body">${page.body}</div>
      ${decisionFaqMarkup(page.faq)}
      <section class="decision-closing"><div><p>Otthon – egyszerűen.</p><h2>${escapeHtml(page.closingTitle)}</h2></div>${decisionAction(page.closingCta)}</section>
    </article>`;
  setCurrent(path);
  bindRoutes();
  return true;
}

function upgradeDecisionPage() {
  const path = normalizePath();
  if (DECISION_PAGE_MAP[path]) renderDecisionPage(path);
}

const decisionNavigateBase = navigate;
navigate = function decisionNavigate(path, replace = false) {
  decisionNavigateBase(path, replace);
  upgradeDecisionPage();
};

window.addEventListener("popstate", upgradeDecisionPage);
upgradeDecisionPage();
