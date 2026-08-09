Szabványkiegészítés v1 — kapuk, terjedelem, hangnem
2026. augusztus 3. · Beillesztendő: master brief §2 után, és a Prompt Library publikációs kapui közé


________________


1. SPEC-QA-001 — Konkrétsági kapu
Mérési egység: egy blokk = egy H2 alatti szövegegység.


Konkrétumnak számít: szám mértékegységgel · dátum vagy időtartam · megnevezett termék, technológia, szabvány vagy cég · megnevezett dokumentum · ár vagy ársáv · földrajzi hely · ellenőrizhető eljárási lépés (ki, mit, mikor).


Nem számít: jelző · "magas színvonal", "korszerű", "megbízható" · folyamatnév tartalom nélkül · ígéret bizonyíték nélkül.


Kapuszabály


* PASS: minden blokkban legalább 1 konkrétum; oldalszinten legalább 8 különböző; a heróban legalább 1.
* FAIL: bármelyik blokk 0 konkrétummal → újraírandó vagy törlendő.
* Külön FAIL: ha az oldal fő ígérete nem tartalmaz ellenőrizhető elemet.


Referencia PASS — imperialholding.hu generálkivitelezés: nm-ársávok, évszám, megépített házak száma, párhuzamos építkezések száma, ajánlati és kezdési átfutás, garanciaidő, e-napló.


Referencia FAIL — a jelenlegi B2B tartalomrendszerből: "A generálkivitelezés terjedelme a jóváhagyott tervből, költségvetésből, ütemből, felelősségi mátrixból és kizárásokból indul." Nulla konkrétum.


________________


2. SPEC-QA-002 — Megkülönböztethetőségi kapu
Kötelező melléklet minden márka- és B2B-oldalhoz: átemelhetőségi tábla — blokk · átemelhető-e igazként testvérmárkára · ha nem, miért nem.


* PASS: a blokkok legfeljebb 20%-a emelhető át igazként másik márkára, és a hero, a fő ígéret és a bizonyítékblokk egyike sem.
* FAIL: a hero vagy a fő ígéret átemelhető.
* Mondatszintű átfedés a testvérmárka azonos funkciójú oldalával legfeljebb 30%. [HIPOTÉZIS: az első öt oldalon kalibrálandó]


Szándékos kivétel: a folyamatkontroll-blokkok (dokumentálás, műszaki vezetői ellenőrzés) átfedhetnek, mert szakmai minimumot írnak le — de nem lehetnek fő üzenetek.


________________


3. SPEC-QA-003 — Gyártásindítási minimum
Egy oldal nem indul gyártásba, amíg nincs meg mind a négy:


1. Három szám, ami csak erre a márkára igaz — az Állításregiszterből, A vagy jóváhagyott B státusszal.
2. Egy jogtisztázott referencia három adattal: méret, szerződéses szerep, kivitelezési idő.
3. Egy publikálható dokumentumminta.
4. Egy mondat, ami a testvérmárkára hamis lenne.


Ha bármelyik hiányzik, a hiány maga a feladat — nem a szövegírás.


________________


4. SPEC-QA-004 — Terjedelmi minimum
Előzetes figyelmeztetés: a karakterszám önmagában rossz mérőszám. Ha egyedül áll, tölteléket termel. Ezért csak a konkrétsági kapuval együtt érvényes: a minimum akkor teljesül, ha a szöveg egyszerre hosszú és sűrű.


Mérés: látható törzsszöveg, szóközökkel; navigáció, lábléc, jogi szöveg és képaláírás nélkül.


Oldaltípus
	Minimum
	Cél
	Főoldal
	4 000
	5 000–7 000
	Szolgáltatás- és pénzoldal
	6 000
	8 000–12 000
	Ágazati / célpiaci oldal
	5 000
	6 000–9 000
	Élethelyzet-oldal
	4 000
	5 000–7 000
	Típusház-adatlap
	1 500
	2 000–3 000
	Konverziós landing
	2 500
	3 000–5 000
	GYIK-oldal
	6 000
	nyitott
	Tudástári cikk
	10 000
	10 000–25 000 (már meglévő szabály)
	

[HIPOTÉZIS: ezek a sávok a magyar B2B és típusház-piac szokásos oldalhosszaiból indulnak. Az első tíz oldal konverziós adata után felül kell vizsgálni.]


Fontos szerkesztési megkötés: a hosszúság nem tolhatja lejjebb a döntési eszközöket. A master brief előírja, hogy a házlista és a kalkulátor kerüljön előre — a hosszú magyarázó szöveg ezért a hajtás alá, nyitható blokkokba vagy a katalógus mögé kerül.


________________


5. SPEC-QA-005 — CTA- és USP-ismétlés
Egy oldal, egy elsődleges cél. Egyetlen elsődleges CTA-típus egy oldalon; másodlagos legfeljebb egy. A több párhuzamos fő CTA a leggyakoribb konverzióromboló hiba.


CTA-ritmus


* A hero elsődleges CTA-ja a hajtás felett, önállóan.
* A master brief 1,5–2 mobilképernyőnkénti konverziós pontjaiból legalább minden második az elsődleges CTA legyen, ne mikroakció.
* Záró CTA kötelező, teljes szélességben, a márkasáv közelében.
* A CTA soha nem lehet folyószövegbe rejtett link. Gomb, saját blokkban, kontrasztos.


USP-ismétlés — háromszor, háromféleképpen


1. Heróban: tömören, az alcím részeként.
2. Önálló, vizuálisan kiemelt blokkban az első képernyő után: a három fő USP, egyenként egy konkrétummal alátámasztva.
3. A záró blokk előtt: más megfogalmazásban, a döntés kontextusában.


Ugyanaz a mondat legfeljebb kétszer szerepelhet szó szerint — kivéve a kanonikus vezérmondatot, amelynek a helye a márkakönyv szerint kötött.


FAIL, ha: az USP-k csak felsorolásként jelennek meg konkrétum nélkül · a fő CTA csak az oldal alján van · három vagy több különböző elsődleges cselekvést kérünk.


________________


6. Hangnem-szabvány
A márkahang márkánként egyedi marad — ezt a Conversation Architecture rögzíti. Az alábbi négy forrás nem a hangot írja felül, hanem a szakmai minimumot adja, ami alá egyik márka sem mehet.
6.1 Magyar mérce
Sipos Zoltán — Kreatív Kontroll. Marketingstratéga, a 2011 óta működő szövegíró és tartalommarketing-ügynökség alapítója és vezetője, a Kontent magazin kiadója, tréner. Amit átveszünk: a szakmai tartalom közérthető magyarra fordítása; a tartalommarketing mint tekintélyépítés, nem cikkgyár; a szöveg mint önálló szakma.


Vavrek Balázs. Direct response copywriter, 2019-ig a Kreatív Kontroll marketingvezetője és a marketingszoveg.com főszerkesztője, ma szabadúszó, elsősorban B2B középvállalatokkal. Amit átveszünk: éles célcsoport — "nem lehet mindenki a célcsoportod"; a kényelmetlen igazság kimondása kerülgetés helyett; értékesítési szöveg mint mérhető eszköz.


A kettő ugyanabból az iskolából jön, ezért nem két külön mérce, hanem egy.
6.2 Nemzetközi alap
StoryBrand (Donald Miller). A vevő a hős, a márka a kalauz; probléma → terv → cselekvésre hívás; a tétnek látszania kell. Amit átveszünk: nem magunkról beszélünk; minden oldalnak van terve és tétje. Amit nem: a hétlépéses formula szó szerinti alkalmazását minden oldalon. Pontosan ettől lesznek egyformák a márkák — ez a jelenlegi hiba egyik forrása.


Dan Kennedy. Direct response alapelvek: mérhető válasz, konkrét ajánlat, "reason why", üzenet–piac illeszkedés, image-hirdetés helyett cselekvés. Amit átveszünk: minden oldalnak legyen mérhető akciója; minden ajánlatnak legyen oka, feltétele és érvényessége. Amit nem: a harsány, felkiáltójeles amerikai hangot. A magyar építőiparban hitelt rombol, és több márkánál a márkakönyv kifejezetten tiltja (Bautica, Casa Moderna, TimberHaus, BMV).
6.3 A közös minimum minden márkára
1. A vevő problémájával nyitunk, nem a cég bemutatásával.
2. Minden ígéret mögött konkrétum áll.
3. A szöveg megmondja, mi a következő lépés.
4. Nincs olyan mondat, amit a testvérmárka is leírhatna.
5. Ha valamit nem tudunk vállalni, kimondjuk — nem hallgatjuk el.


________________


7. CLAUDE.md
A repó gyökerébe, egyetlen igazságforrással. A fájl tartalma külön dokumentumban.


Ezt össze kell vetni a tényleges AGENTS.md tartalmával. Ha az AGENTS.md már tartalmazza a négy pontot, a CLAUDE.md maradjon két sor.


________________


8. Sorrend
1. Árellentmondás eldöntése (Állításregiszter) — ez blokkol mindent.
2. Ez az öt kapu beillesztése a master briefbe és a Prompt Library gate-listájába.
3. SPEC-QA-003 ráfuttatása a karanténban lévő oldalakra — kiderül, melyik üres adathiány, és melyik szövegírás miatt.
4. CLAUDE.md az AGENTS.md ellenőrzése után.
