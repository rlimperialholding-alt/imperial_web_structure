# Commercial Integration v1.0 – UAT

## Kötelező discovery UAT

1. Új fejlesztési kérést kell rögzíteni keresési kifejezésekkel és jelölt artifactokkal.
2. Meglévő kanonikus modul esetén csak reuse/extend/integrate/repair döntés engedhető tovább.
3. Jóváhagyás nélküli kiadás státusza `discovery_blocked` legyen.
4. Tulajdonosi kivétel nélkül új párhuzamos ModuleKey ne legyen kiadható.

## Contract Generator UAT

1. A forrásállapot mutassa a v0.4 verziót és az egyező ZIP-hasht.
2. Mind az öt sablon legyen hash-ellenőrzött.
3. Valós, jóváhagyott projektadatból készüljön szerződéscsomag.
4. A ZIP és manifest jelenjen meg a dokumentumtárban.
5. A szerződésprojekció jelenjen meg a Projekt 360°-ban.
6. Ugyanazon szerződésszám ismételt generálása legyen blokkolt.
7. Aláírási bizonyíték után `CONTRACT_SIGNED` esemény induljon a PM, Finance és MyImperial felé.

## ChangeControl UAT

1. Partneri változásbejelentésből csak intake keletkezzen.
2. A ChangeControl forrásmodul státusza jelenjen meg a Workspace-ben.
3. A Workspace ne módosíthasson közvetlenül scope-ot, árat, fedezetet vagy munkakezdést.
4. Ügyfél-elfogadás, munkakezdési engedély és teljesítés eseményei idempotensen kerüljenek be.
5. Finance-, Calendar-, Procurement- és MyImperial-adapterek valós célkörnyezeti UAT-ja történjen meg.

## Élesítési minimum

- öt valós projekt;
- élő CRM- és ChangeControl-forráskapcsolat;
- e-aláírás és kettős kézbesítési bizonyíték;
- jogosultsági, adatvédelmi és mentés-visszaállítási ellenőrzés;
- tulajdonosi production jóváhagyás.
