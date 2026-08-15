# Imperial Tender Partner Portal v1.0 – as built

## Hatókör

A modul a TenderMail meghívási és kézbesítési rétegét valódi ajánlatkérési
üzleti folyamattal egészíti ki. A TenderMail külső szolgáltató nélkül továbbra
is fail-closed, a partnerportál azonban meghívólinkkel teljesen tesztelhető.

## Folyamat

1. A projektmenedzser vagy beszerzési jogosultságú felhasználó kanonikus
   `ProjectID`-hez tendercsomagot hoz létre.
2. Meghatározza a terjedelmet, a kérdezési és beadási határidőt, pénznemet,
   valamint a 100%-ra záró értékelési súlyokat.
3. Partnereket hív meg közvetlenül vagy TenderMail-címzettek szinkronjával.
4. A partner egyedi tokennel látja a saját tenderét, ajánlatát és kommunikációját.
5. A partner tételes nettó árat, ÁFÁ-t, átfutást, garanciát, összefoglalót,
   kizárásokat és ellenőrzött mellékleteket rögzít.
6. Határidőn belül bead, visszavon és új verziót készít; határidő után a szerver
   minden módosítást blokkol.
7. A projektmenedzser lezárja az ajánlatfogadást és súlyozott értékelést készít.
8. Csak tulajdonos, ügyvezető vagy platform-admin hirdethet eredményt, legalább
   egy dokumentált értékelés és vezetői indoklás után.

## Adatvédelem és audit

- A partner csak a saját meghívását, ajánlatát, mellékleteit és neki címzett
  vagy minden partnernek szóló üzeneteket látja.
- A belső feljegyzés soha nem jelenik meg a partnerportálon.
- Feltöltés: PDF/XLSX/DOCX/JPG/PNG, legfeljebb 25 MB, kiterjesztés–MIME–belső
  szerkezet egyeztetés, Office ZIP-bomba és titkosítás elleni korlátok, SHA-256.
- A feltöltés még a lemezre írás előtt ClamAV `INSTREAM` vizsgálaton megy át.
  Scanner-hiba, timeout, ismeretlen válasz vagy hiányzó konfiguráció esetén a folyamat
  fail-closed (`503`), pozitív malware-találatnál elutasít (`400`).
- Csak `clean` scan-eredményű melléklet tölthető le. Minden letöltés újraellenőrzi a
  tárolási gyökérútvonalat és az SHA-256-ot; eltérés vagy régi `legacy_unverified`
  rekord esetén a letöltés blokkolt és auditált.
- A scan-állapot, engine, engine-verzió, időpont és opcionális malware-szignatúra
  perzisztált. A 0068 migráció a régi fájlokat nem minősíti visszamenőleg tisztának.
- Minden létrehozás, mentés, beadás, visszavonás, tisztázás, értékelés és
  odaítélés auditnapló-bejegyzést készít.
- Közzétételkor projekt-esemény és feladat keletkezik; eredményhirdetéskor a
  kapcsolódó esemény és feladat lezárul.
- A tendercsomagot, meghívót és formális hiánypótlást módosító tranzakciók
  PostgreSQL `FOR UPDATE` sorszintű zárral, egységes tender→meghívó sorrendben
  futnak. Ez sorosítja az egyidejű mentés/beadás/visszavonás, linkcsere,
  tenderzárás, értékelés és odaítélés állapotváltásait.

## Szerepkörök

- Operatív kezelés és értékelés: projektmenedzser, pénzügy, műszaki előkészítő,
  ügyvezető, tulajdonos, platform-admin.
- Vezetői odaítélés: tulajdonos, ügyvezető, platform-admin.
- Külső partner: kizárólag egyedi tendermeghívó-token, belső munkatér nélkül.

## Külső release-kapu

Az éles meghívó-e-mail küldéshez hitelesített SPF/DKIM/DMARC és konfigurált
provider-adapter szükséges. Enélkül a rendszer csak biztonságos szimulációt
enged, de a partnerportál közvetlen, egyedi linkkel UAT-ra használható.

Az éles mellékletkezeléshez `TENDER_AV_MODE=clamav`, elérhető, frissített ClamAV
szolgáltatás és `TENDER_CLAMAV_HOST` szükséges. A determinisztikus teszt-scanner
kizárólag `ENVIRONMENT=test` mellett indul; más környezetben fail-closed. A ClamAV
szolgáltatás telepítéséig a mellékletfeltöltés szándékosan nem release-ready.

## UAT- és release-állapot – 2026-08-15

- Célzott szintetikus UAT: 17/17 PASS (`test_tender_portal.py`,
  `test_tender_evidence_security.py`, `test_tender_mail.py`). Lefedett utak:
  procurement/projektmenedzser, külső partner/alvállalkozó, tiltott belső
  alvállalkozói hozzáférés, no-bid, visszavonás és új verzió, link
  rotate/revoke/expire, melléklet-típus/AV/hash/scope, tisztázás, értékelés,
  vezetői odaítélés, esemény/feladat és audit.
- Teljes Platform Core regresszió azonos kódállapoton: 555/555 PASS, 5 ismert,
  nem blokkoló dependency-warning, 2740,55 s. A futás nem írt pytest cache-t,
  bytecode-ot, reportot, screenshotot vagy tartós tesztadatbázist.
- Friss adatbázis-migráció 0001→0068 PASS; a sémaellenőrző mind a 12 kötelező
  Tender-táblát és minden kötelező lifecycle/AV oszlopot megtalálta.
- PostgreSQL zárolási SQL bizonyíték PASS: a módosító csomaglekérdezés `FOR
  UPDATE` klauzussal fordul, az olvasási lekérdezés nélküle.
- A szerver jelenlegi sémája 0064; éles kiadás előtt Hetzner-only mentés és
  visszaállítás-ellenőrzés után 0065→0068 migráció szükséges. Ez jelenleg nem
  történt meg.
- Nyitott kiadási kapu: valódi ClamAV-adapter és frissítési/riasztási felügyelet.
- Nyitott kiadási kapu: hitelesített levélküldő domain és provider-adapter.
- Nyitott biztonsági kapu: a gateway és az alkalmazáskiszolgáló access logja
  nem őrizheti meg a partnerlink `recipient` bearer értékét; ezt éles
  meghívás előtt logkonfigurációval és negatív smoke-kal kell bizonyítani.
- Nyitott UAT-kapu: támogatott asztali és mobil böngészőkön kézi
  billentyűzetes/reszponzív ellenőrzés. Valódi tenderküldés továbbra sem engedett.
