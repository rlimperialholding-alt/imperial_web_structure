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
  perzisztált. A 0066 migráció a régi fájlokat nem minősíti visszamenőleg tisztának.
- Minden létrehozás, mentés, beadás, visszavonás, tisztázás, értékelés és
  odaítélés auditnapló-bejegyzést készít.
- Közzétételkor projekt-esemény és feladat keletkezik; eredményhirdetéskor a
  kapcsolódó esemény és feladat lezárul.

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
