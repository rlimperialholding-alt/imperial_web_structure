# Imperial Intelligence Workspace v1.0 – As-Built

## 1. Cél

Az Imperial Intelligence különálló moduljainak egységes, napi használatú webes munkakörnyezete. A Workspace nem másolja le a CRM, Finance, PM Cockpit, Import Center vagy más forrásmodul üzleti logikáját. A forrásmodulok tranzakcióit közös ProjectID, esemény, feladat, dokumentum és keresési nézet formájában jeleníti meg.

## 2. Megvalósított felületek

### Kezdőlap
- szerepkörhöz igazított személyes munkatér;
- nyitott, lejárt és aznap esedékes feladatok;
- blokkolt projektek és pénzügyi hatás;
- vezetői események;
- legutóbbi projektek és dokumentumok;
- modulindító és integrációs állapot.

### Action Center
- minden modulból érkező feladat egységes listája;
- állapot-, prioritás-, projekt- és szöveges szűrés;
- feladat lezárása, folyamatba helyezése és blokkolása;
- teljes auditnapló;
- API-alapú feladatfrissítés.

### Projekt 360°
- projektösszefoglaló és kockázati helyzet;
- nyitott feladatok és rendszerközi eltérések;
- ProjectFact tényadatok modulonként;
- dokumentumok;
- esemény-idővonal;
- modulobjektumok;
- ProjectID-alapú API.

### Központi dokumentumtár
- Google Drive és más források dokumentumreferenciái;
- ProjectID, kategória, jóváhagyási és ellenőrzési státusz;
- felelős, verzió, lejárat és tartalmi összefoglaló;
- jóváhagyási és verifikációs művelet;
- auditált dokumentumregisztráció.

### Központi kereső
- projekt, feladat, esemény, dokumentum és importált vállalati rekord keresése;
- forrás- és ProjectID-kontekstuális találatok;
- csoportosított UI- és JSON API-válasz.

## 3. Adatmodell

Új tábla: `ws_documents`.

A meglévő alábbi objektumokat használja újra:
- `cc_projects`;
- `cc_tasks`;
- `cc_events`;
- `cc_project_facts`;
- `cc_project_object_states`;
- `cc_consistency_issues`;
- `ic_canonical_records`;
- `cc_modules`;
- `cc_audit_log`.

## 4. Fő webes útvonalak

- `/` – személyes Workspace;
- `/executive` – a korábbi vezetői cockpit változatlan logikával;
- `/tasks` – Action Center;
- `/projects/{ProjectID}` – Projekt 360°;
- `/documents` – dokumentumtár;
- `/search` – központi kereső.

## 5. Új API-k

- `GET /api/workspace/summary`;
- `GET /api/tasks`;
- `POST /api/tasks/{TaskID}`;
- `GET /api/search`;
- `GET /api/projects/{ProjectID}/360`;
- `POST /api/documents`.

## 6. Biztonsági és működési elvek

- a Workspace nem írja felül automatikusan a forrásmodul tranzakcióit;
- minden feladat- és dokumentummódosítás auditált;
- az ügyféloldali és belső üzleti adatok meglévő elválasztása változatlan;
- production környezetben PostgreSQL, HTTPS, hosszú session-secret és API-token kötelező;
- a Drive-fájlok ebben a kiadásban referenciaként kapcsolódnak; élő kétirányú Drive-adapter az élesítési szakasz része.

## 7. Felület

- Imperial sötétkék–arany vállalati karakter;
- fix, csoportosított oldalsó navigáció;
- globális kereső a fejlécben;
- 1440 px asztali és reszponzív mobil/tablet kialakítás;
- 1440 px ellenőrzésnél nincs vízszintes kilógás;
- a négy új főnézet renderelése JavaScript-hiba nélkül megtörtént.

## 8. Korlátok és élesítési függőségek

- nincs éles SSO/2FA;
- nincs valós Gmail, Drive, Calendar, Billingo, NAV vagy banki adapter;
- a modulok többsége még `not_connected` állapotú;
- három valós ProjectID-val végzett tulajdonosi UAT továbbra is szükséges;
- a dokumentumok jogosultsági öröklését az éles Drive- és IAM-kapcsolatban kell véglegesíteni.
