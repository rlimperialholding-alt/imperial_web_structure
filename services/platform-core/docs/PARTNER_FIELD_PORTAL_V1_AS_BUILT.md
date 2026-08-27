# Imperial Intelligence – Alvállalkozói Helyszíni Portál v1.0

## Cél
Nagyon egyszerű, mobilról használható, projektre és munkacsomagra korlátozott felület az alvállalkozói brigádok számára.

## Funkciók
- külön rövid kódos belépés;
- csak a hozzárendelt projekt, munkacsomag és saját brigád látható;
- személyenkénti érkezés és távozás időbélyeggel;
- opcionális GPS-koordináta, pontosság és eszközazonosító;
- napi haladás százalékkal, mennyiséggel és szöveges leírással;
- probléma- és STOP-bejelentés;
- változás-/eltérésbejelentés ChangeControl intake-ként;
- helyszíni JPG, PNG és WEBP fotók 12 MB-os korláttal, tartalomellenőrzéssel és SHA-256 lenyomattal;
- szöveges offline piszkozatmentés PWA-ban;
- PM Cockpit belső felülvizsgálat és jóváhagyás.

## Kötelező üzleti korlátok
1. Az alvállalkozói készültség csak jelentett adat; PM-jóváhagyásig nem írja felül a munkacsomagot.
2. A változásbejelentés nem jelent megrendelést, pótmunka-elfogadást, scope-, ár- vagy határidőmódosítást.
3. Minden külső partneradat `partner_connect` forrásmodullal, auditnaplóval és ProjectID-val kerül be.
4. A partner nem láthat pénzügyi, ügyfél-, más partner- vagy teljes projektportfólió-adatot.
5. A jelenléti felület belső bizonyíték- és operációs rendszer; nem helyettesíti az e-naplót, a munkaügyi nyilvántartást vagy a beléptetőrendszert.
6. Fotók production környezetben objektumtárolóba, malware-szűréssel, megőrzési szabállyal és jogosultságos URL-lel kerülnek.

## Production előtt
- vállalati Partner Connect identitás és 2FA/PIN-élettartam;
- HTTPS és rate limit;
- objektumtároló és vírusellenőrzés;
- GDPR-adatkezelési tájékoztató és megőrzési idő;
- helyadat használatának jogi és munkajogi ellenőrzése;
- három valós brigáddal UAT;
- e-napló export-/átadási adapter.
