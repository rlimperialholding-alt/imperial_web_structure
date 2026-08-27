# Imperial Holding Copy Gate pilot

Pilot manifest:
`data/copy_gate/imperial_pilot_v1.json`

## Lefedett assetek

- főoldali hero és első három önálló szekció;
- teljes 126 m²-es HousePlan termékoldal;
- kampány landing;
- hét külön Meta kreatívszöveg;
- Google RSA;
- három follow-up e-mail;
- chatbot nyitó és kifogáskezelő ág.

Összesen 15 asset. A manifest minden assethez külön címet, szövegirányt és layout
signature-t ad; exact cím- és layoutduplikációt a pilot regression teszt tilt.

## Bizonyíték

`tests/test_imperial_copy_gate_pilot.py` mind a 15 assethez külön CopyBriefet,
scorecardot és Gate 1 eredményt állít elő. Minden eredmény legalább 92/100 és
`APPROVED`, de ettől egyik sem publikálható automatikusan: a specialistakapu,
emberi szerkesztői és tulajdonosi approval továbbra is kötelező.

A negatív revision auditot a `tests/test_copy_gate_engine.py` és
`tests/test_content_quality_workflow.py` igazolja: generikus/márkakevert,
duplikált, verzióhibás, proof-hiányos, message-mismatch és approval-hiányos
tartalom blokkolódik, konkrét repair ticketet és auditot kap.

A teljes ellenőrzési eredmény a `COPY_GATE_TEST_REPORT.md` fájlban található.

## Korlát

A pilot üzleti és forrásazonosítói szintetikus UAT rekordok. Production claim,
ár, feltétel, vizuális jog és owner approval nincs beégetve; ezeket az aktív
registryből és secret-managed adapterekből kell betölteni.
