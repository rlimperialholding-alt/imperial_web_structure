# Imperial Intelligence Control Center v1.0 – As-Built

## Rendszerszerep

A Control Center a CRM, Contract Generator, PM Cockpit, Smart Calendar, MyImperial, ChangeControl, Partner Connect, Procurement, Finance, Imperial Care és a műszaki/értékesítési modulok fölött közös ProjectID-, esemény-, feladat-, objektumállapot-, adatkonzisztencia- és kiadásfelügyeleti réteget biztosít.

## Megvalósított adatobjektumok

- User
- ModuleRegistry
- ProjectRegistry
- EventRecord
- ProjectObjectState
- TaskRecord
- OutboxMessage
- ProjectFact
- ConsistencyIssue
- ReleaseRecord
- ArtifactRecord
- EnvironmentRecord
- DeploymentRecord
- PilotRun
- AuditLog

## Eseményfeldolgozás

1. A forrásmodul saját tranzakcióját lezárja.
2. EventID és DedupeKey alapján eseményt küld.
3. A Control Center idempotensen befogadja.
4. Frissíti a ProjectID állapotát és objektumvetületét.
5. Kockázatos eseménynél felelőst, határidőt és feladatot képez.
6. A célmodulok felé outbox-bejegyzéseket készít.
7. Célrendszeri hiba retry, majd dead-letter állapotot eredményez.

## Adatkonzisztencia-szabályok

- Contract Generator jóváhagyott bevétel ↔ Finance jóváhagyott bevétel;
- PM pénzügyi–műszaki ütemterv számlázási hash ↔ Finance számlázási hash;
- ChangeControl jóváhagyott változtatási bevétel ↔ Finance változtatási bevétel;
- Procurement vállalt kötelezettség ↔ Finance beszerzési kötelezettség;
- Procurement átvett mennyiség ↔ Finance számlázott mennyiség;
- Smart Calendar lezárt fázis ↔ PM műszakilag elfogadott fázis;
- MyImperial ügyféldöntés ↔ PM belső döntési státusz.

A Control Center nem választ automatikusan „igaz” értéket. Eltérés esetén egyeztetési ügyet nyit, majd egyezéskor lezárja.

## Kiadási kapu

Production státusz csak akkor engedélyezett, ha:

- a forrás-ZIP és SHA-256 artifact Drive-on ellenőrzött;
- minden automatizált teszt sikeres;
- a migráció tesztelt;
- az UAT jóváhagyott;
- a biztonsági ellenőrzés megtörtént;
- a mentés-visszaállítás tesztelt;
- a tulajdonos jóváhagyta.

## Verzió

- Control Center: 1.0.0
- Platform: 4.0.0
- Alembic: 20260719_0001
