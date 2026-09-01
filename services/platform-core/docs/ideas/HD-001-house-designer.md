# HD-001 — Háztervező termékötlet

Állapot: ACCEPTED FOR SPECIFICATION  
Osztályozás: CRITICAL  
Kezdeményező: üzleti tulajdonos  
Dátum: 2026-08-10

## Cél

Egy önállóan értékesíthető, több-bérlős alkalmazás és az Imperial Intelligence-be beágyazott `house-designer` modul közös kanonikus szolgáltatásmaggal. Az ügyfél típustervből vagy üres vászonról, méretpontosan állít össze egy legfeljebb háromszintes lakóház-koncepciót, műszaki konfigurációt, látványtervet, költségbecslést és kivitelezési ütemtervet, majd azt konzultációra és megrendelési szándékként továbbítja.

## Kötelező termékígéret

- A szerkesztő nem hozhat létre geometriailag érvénytelen állapotot.
- A rendszer nem állíthatja egy tervről, hogy megépíthető, ha az alkalmazandó országos és helyi szabályok, a telek és az ellenőrzés bizonyítéka nem teljes.
- Ismeretlen szabály vagy telekadat esetén a vázlat szerkeszthető, de a `COMPLIANT`, `ORDERABLE` és `SUBMITTED` állapot fail-closed módon tiltott.
- A kimenet koncepció és előzetes becslés; nem helyettesíti a jogosult tervező telekre adaptált építészeti dokumentációját vagy a hatósági eljárást.
- Minden számítás verziózott bemenetből reprodukálható és auditálható.

## Fő képességek

1. Típusterv kiválasztása, klónozása vagy új terv indítása.
2. Méretpontos, rácsra illesztett 2D alaprajzszerkesztés 1–3 szinttel, tetőtérrel, helyiségekkel, falakkal, nyílászárókkal, lépcsővel és függőleges maggal.
3. Valós idejű geometriai, használhatósági és szabályellenőrzés.
4. Telek és helyrajzi szám alapján verziózott TÉKA/átmeneti OTÉK, HÉSZ, településképi és védettségi szabálykészlet kiválasztása.
5. Tételes vagy csomagalapú műszaki konfiguráció: technológia, készültségi fok, tető, alapozás, födém, lépcső, gépészet, energetika, burkolatok és egyéb tételek.
6. Prompttal módosítható, geometriához kötött látványterv-verziók.
7. Ár- és időterv-snapshot, bizonytalansági sávokkal és lejárattal.
8. Ügyféljóváhagyás, megrendelési szándék, CRM-lehetőség és konzultációs időpont.
9. MyImperial követhetőség és belső értékesítői/tervezői felülvizsgálat.

## Nem cél az első kiadásban

- Automatikus engedélyezési vagy hatósági benyújtás.
- Jogosult tervező felelősségének kiváltása.
- Ellenőrizetlen HÉSZ-szövegből automatikus, joghatással bíró szabályalkotás.
- Statikai, talajmechanikai vagy teljes szakági kiviteli terv automatikus elkészítése.

