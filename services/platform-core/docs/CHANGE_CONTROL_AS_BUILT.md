# Change Control – as-built

## Forrás és rendszerhatár

A megvalósítás kanonikus forrása a Drive-on tárolt „ChangeControl v0.1 –
pótmunka- és változtatáskezelő, vállalati bevezetés és élesítési követelmények”.
A natív szolgáltatás a ChangeID és verzió üzleti tulajdonosa; a Commercial
Integration, Finance, Smart Calendar, Procurement, CRM és MyImperial esemény- és
projekciós kapcsolatot kap.

## Kötelező folyamat

- közös kanonikus ProjectID és változatlan ChangeID;
- minden tartalmi vagy ármódosítás új, immutábilis snapshot-hashű verzió;
- tételes mennyiség, egység, önköltség, eladási ár és korai közvetlen költség;
- nettó önköltség, nettó/bruttó eladási ár, ÁFA és fedezet automatikus számítása;
- 35% alatti fedezet, hiányos scope/tételsor vagy elégtelen ügyfélelőleg fail-closed STOP;
- műszaki → pénzügyi → nagy érték/határidő esetén vezetői jóváhagyási sorrend;
- a készítő önjóváhagyása és ugyanazon személy több kötelező kapuja tiltott;
- a konkrét verzió és SHA-256 hash MyImperial ügyféldöntési kérésként jelenik meg;
- ügyfél-elfogadás nélkül külön munkakezdési engedély és Smart Calendar elem nem készül;
- dokumentált teljesítés zárja le a változtatást és indítja a pénzügyi/számlázási eseményt;
- új verzió minden belső jóváhagyást, ügyféldöntést és munkakezdési engedélyt nulláz.

## Dokumentumcsomag és hozzáférés

- belső ellenőrzés indításakor verzióhoz kötött belső PDF készül;
- a végső belső jóváhagyás után külön ügyfél-PDF készül önköltség és fedezet nélkül;
- mindkét fájl a központi runtime dokumentumtárba kerül, SHA-256 lenyomattal és
  `WorkspaceDocument` rekorddal;
- a belső PDF csak ChangeControl-szerepkörrel, az ügyfél-PDF kizárólag aktív
  MyImperial projekt-hozzáféréssel tölthető le;
- minden letöltés újraszámolja és ellenőrzi a fájl SHA-256 lenyomatát;
- a MyImperial projektoldal a jóváhagyott ügyfélcsomagot közvetlenül megjeleníti.

## Konzervatív vezetői alapkapu

A specifikáció a „nagy érték” és „jelentős határidőhatás” fogalmát számszerű
küszöb nélkül rögzíti. A fail-closed alapérték nettó 5 000 000 Ft vagy legalább
5 nap hatás. A küszöb a felületen látható; későbbi policy-verzióban központi,
verziózott konfigurációvá emelendő.

## Bizonyító eszközök

- `tests/test_change_control_business.py`;
- `scripts/verify_change_control_schema.py`;
- `scripts/seed_change_control_uat.py`.
