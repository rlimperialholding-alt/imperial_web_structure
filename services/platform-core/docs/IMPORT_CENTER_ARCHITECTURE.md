# Enterprise Import Center – as-built architektúra

## Cél

A vállalat meglévő adatait nem egyszerű fájlmásolással, hanem tartalmilag értelmezve, forrásbizonyítékkal és jóváhagyási kapuval emeli be az Imperial Intelligence-be.

## Folyamat

1. **Source registry:** Gmail, Drive, Sheets, korábbi CRM vagy kézi fájl.
2. **Import job:** egy körülhatárolt forrás, időszak és üzleti cél.
3. **Import item:** üzenet, melléklet, dokumentum, táblázat vagy connector payload.
4. **Extraction/staging:** rekordokra bontás, normalizálás és tartalmi osztályozás.
5. **Evidence:** forrásazonosító, URL, fájlnév, SHA-256 és kinyerési módszer.
6. **Validation:** kötelező mezők, üzleti kulcs, ProjectID, biztonsági pontszám.
7. **Deduplication:** domain + entitástípus + normalizált külső kulcs.
8. **Human gate:** jóváhagyás, javítás, célmodul- vagy ProjectID-módosítás.
9. **Commit:** canonical record, ProjectRegistry és ProjectFact frissítés.
10. **Rollback:** a commit-csomagban létrehozott vagy felülírt canonical rekord visszaállítása.

## Domain és célmodul

| Domain | Példák | Célmodul |
|---|---|---|
| finance | számla, fizetés, terv, cashflow | Finance Intelligence |
| project | projekt, státusz, mérföldkő | PM Cockpit / Control Center |
| partner | cég, kapcsolattartó, alvállalkozó | Partner Connect |
| customer | ügyfél, lead, megrendelő | CRM |
| procurement | tender, ajánlatkérés, munkacsomag | Procurement |
| contract | szerződés, szerződésszám | Contract Generator |
| product_data | márka, technológia, ár, csomag | BuildConfig |
| document | általános dokumentumtényező | Control Center |

## AI szerepe

Az architektúra kétlépcsős: a connector vagy későbbi vállalati LLM-adapter strukturált jelölteket adhat át, a platform pedig determinisztikusan normalizál, validál és deduplikál. LLM-kimenet önmagában nem kerülhet commitra; minden következtetés staging státuszú és emberileg felülbírálható.

## Biztonsági minimum

- legkisebb szükséges OAuth-scope;
- kijelölt Drive-mappák, Gmail-címkék/keresések és dátumtartományok;
- belső API-token;
- 20 MB-os fájllimit és engedélyezett formátumlista;
- auditnapló;
- célmodul-jogosultság;
- érzékeny adatok külön megőrzési és maszkolási szabálya az éles adapterben.
