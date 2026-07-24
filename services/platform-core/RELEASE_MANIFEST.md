# Imperial Intelligence Commercial Integration v1.0 – Release Manifest

- Kiadás: 2026-07-19
- Commercial Integration verzió: 1.0.0
- Alkalmazásverzió: 1.5.0
- Platformverzió: 5.0.0
- Alembic head: `20260719_0006`
- Állapot: tesztelt, futtatható development/UAT release; production deployment még nem történt meg.

## Kanonikus források

### Contract Generator

- Kanonikus modul: `contract_generator`
- Forrásverzió: `0.4.0`
- Drive FileID: `1kL92i1Z8Zk5V_1W4wmTbJB0pRAVVhSHV`
- Forrás-ZIP SHA-256: `3634378bbc90f885b54e787f6de06e57cabf4d6a594e1351463388814e191a42`
- Felhasználási döntés: `integrate`
- Módosított üzleti motor: nincs

### ChangeControl

- Kanonikus modul: `change_control`
- Forrásverzió: `0.1.0`
- Drive dokumentumazonosító: `1h-_5X0-zHZmVSKYdg5t13rZQQktZRHlcXYWUZYyvXCo`
- Felhasználási döntés: `integrate`
- Új ár-, fedezet-, scope-, jóváhagyási vagy munkakezdési motor: nincs

## Új funkciók

- kötelező kanonikus újrafelhasználási discovery gate;
- `DevelopmentDiscoveryRecord` és auditált review-folyamat;
- release-blokkolás jóváhagyott discovery nélkül;
- Contract Generator v0.4 hash-ellenőrzött adapter;
- Workspace-dokumentumregisztráció és projektállapot-projekció;
- csendes szerződésduplikáció blokkolása;
- ChangeControl esemény- és állapotprojekció;
- Commercial Integration és Reuse Gate webes felület.

## Tesztbizonyíték

- 80/80 alkalmazásteszt sikeres;
- a változtatás nélkül átvett Contract Generator saját további 15 résztesztje sikeres;
- tiszta Alembic-upgrade sikeres;
- adatbázistáblák száma: 46;
- asztali 1440 px és mobil 390 px renderellenőrzés: túlnyúlás és JavaScript-hiba nélkül;
- Contract Generator ZIP- és mastersablon-hash ellenőrzés sikeres.

## Production előtt szükséges

- PostgreSQL és vállalati IAM/SSO;
- élő CRM-, Gmail-, Drive-, e-aláírási és kézbesítési adapter;
- élő ChangeControl API vagy eseményadapter;
- legalább öt valós projekt integrációs UAT-ja;
- biztonsági, adatkezelési és mentés-visszaállítási próba;
- tulajdonosi production jóváhagyás.
