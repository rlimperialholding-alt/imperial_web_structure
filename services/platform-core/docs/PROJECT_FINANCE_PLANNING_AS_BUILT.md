# Projektpénzügyi tervezés és forecast – as-built

## Cél és határ

A projektpénzügyi tervezés a Financial Control és Finance Intelligence közös,
kanonikus baseline-folyamata. Projektenként egy nyitott tervverzió lehet; a
benyújtott verzió nem írható át, csak a lezárt változat klónozásával készíthető
új verzió.

## Megvalósított üzleti folyamatok

- szerződéses nettó bevétel és jóváhagyott változásbevétel;
- tételes költségkódok budget, lekötött, tény és estimate-to-complete mezőkkel;
- külön tartalékkeret és 0–100% közötti projekt-célfedezet;
- időszakos bevételi és kiadási cashflow forecast, committed és actual állapottal;
- automatikus budget-, forecast-, fedezet-, eltérés- és kumulált cashflow-számítás;
- projektmenedzseri benyújtás után pénzügyi, majd vezetői jóváhagyás;
- a benyújtó, a pénzügyi ellenőr és a vezetői jóváhagyó három külön személy;
- automatikus pénzügyi és ügyvezetői feladatkártya, jóváhagyáskor automatikus zárás;
- célfedezet alatti terv csak legalább 20 karakteres vezetői kivételindoklással;
- jóváhagyáskor kanonikus `ProjectObjectState` létrehozása;
- pénzügyi vagy vezetői elutasítás kötelező indoklással, feladatlezárással és újraverziózással;
- korábbi baseline automatikus `superseded` állapota az új verzió jóváhagyásakor;
- auditnapló a létrehozásról, tételekről, benyújtásról és mindkét jóváhagyásról;
- jóváhagyott baseline-ok közvetlen megjelenítése a pénzügyi intelligencia oldalon.

## Jogosultság

- `project-manager`: terv, költség- és cashflow-sor létrehozása, benyújtás és új verzió;
- `finance`: szerkesztés, benyújtás és pénzügyi jóváhagyás;
- `managing-director`: vezetői jóváhagyás és fedezeti kivétel;
- `owner`, `platform-admin`: teljes folyamat;
- a teljes folyamat-jogosultság sem engedi ugyanazon személy több kötelező kapuját;
- más szerepkör a pénzügyi útvonalakat nem érheti el.

## Bizonyító tesztek és üzemeltetés

- `tests/test_project_finance.py`: számítás, immutabilitás, verziózás, szerepkör,
  feladatkártya, projektállapot és fedezeti kivételkapu;
- `scripts/verify_project_finance_schema.py`: a három új tábla és kötelező oszlopok;
- `scripts/seed_project_finance_uat.py`: idempotens, név szerint UAT-ként jelölt,
  jóváhagyott szerveroldali tesztbaseline.

Az UAT-adatok szintetikusak, nem könyvelési bizonylatok és nem helyettesítik a
banki, Billingo- vagy főkönyvi integráció későbbi egyeztetését.
