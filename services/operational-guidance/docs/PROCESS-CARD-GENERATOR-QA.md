# Operational Guidance Engine v0.5.0 – QA jegyzőkönyv

Dátum: 2026-07-23

## Automatikus tesztek

- teljes Integration Hub tesztcsomag: **37/37 PASS**;
- 99 ProcessID és 99 ChecklistTemplateID egy-egy megfeleltetése: PASS;
- kizárólag az öt valós munkakör használata: PASS;
- Process Card és checklist közös Directus record sinkje: PASS;
- emberi Process Card-generálás: PASS;
- PDF- és PNG-generálás: PASS;
- jóváhagyási sor és verziózott publikálás: PASS;
- checklist `NEM` validáció, felelős és határidő: PASS;
- blocking `NEM` → HOLD: PASS;
- evidence és beküldési kapu: PASS;
- jóváhagyás → CLOSED → `can_proceed=true`: PASS;
- checklist-szabály változása → új Process Card-verzió: PASS;
- Directus-, Drive- és Gmail-adapter szerződések: PASS tesztadapterrel.

## Teljes katalógus artefaktum-QA

A `scripts/qa_operational_guidance.py` mind a 99 folyamatot generálja. Folyamatonként ellenőrzi:

- Process Card PDF: pontosan egy oldal és kinyerhető szöveg;
- checklist PDF: pontosan egy oldal és kinyerhető szöveg;
- mindkét PNG létezése, mérete és felbontása;
- üres vagy hiányzó artefaktum.

Ellenőrzött mennyiség: 99 Process Card + 99 checklist, összesen 396 PDF/PNG artefaktum. Talált hiba: **0**.

## Vizuális ellenőrzés

Külön megnyitva ellenőrzött projektfolyamat: `PRJ-003`. A Process Card és a checklist nem tartalmazott levágott szöveget, átfedést, hibás ékezetet vagy üres mezőt. A korábbi hibás kéthasábos szélességszámítás javítva lett.

## Éles integrációs korlát

A helyi motor és az adapterek elkészültek, de valódi vállalati Directus-token, Google service account, delegált Gmail-felhasználó és cél Drive-jogosultság nélkül production end-to-end teszt nem állítható. Éles státusz csak a `docs/DEPLOYMENT.md` szerinti staging UAT után adható.
