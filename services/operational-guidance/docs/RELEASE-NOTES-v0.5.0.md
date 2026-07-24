# Imperial Intelligence Integration Hub v0.5.0 – kiadási jegyzet

## Új főmodul

Az **Operational Guidance Engine** egyesíti a Process Card Generatort és az operatív Checklist Engine-t. A két funkció ugyanazt a 99 folyamatból álló kanonikus katalógust, az öt valós munkakört, a GateID-kat, a jóváhagyást és a verziókezelést használja.

## Fő funkciók

- 99 ProcessID és 99 ChecklistTemplateID teljes összerendelése;
- Process Card PDF/PNG/JSON és checklist PDF/PNG/JSON közös bundle-ben;
- Directus folyamat- és checklist-forrásadapter;
- közös Directus record sink a kártyaverziókhoz, sablonokhoz és példányokhoz;
- ügyvezetői approval és verziózott Drive-publikálás;
- Gmail approval értesítő;
- IGEN / NEM / N.A. checklist, evidence és audit;
- blocking NEM → HOLD;
- csak CLOSED checklist engedi a workflow továbbhaladását;
- az utolsó jóváhagyott checklist-verzió marad hatályos az új draft jóváhagyásáig;
- checklist- vagy folyamatváltozás automatikusan új Process Card-draftot indít;
- Directus webhook és 15 perces Celery safety-net;
- n8n referenciafolyamat;
- közös Docker runtime volume és folyamatonkénti zárolás a duplikált verziók ellen.

## Ellenőrzött állapot

- Pytest: 37/37 PASS;
- teljes katalógus: 99/99 folyamat és checklist;
- 396 PDF/PNG artefaktum gépi vizsgálata;
- 0 hiányzó, üres, többoldalas vagy szöveg nélküli artefaktum;
- külön vizuális ellenőrzés PRJ-003 Process Cardon és checklisten.

## Nem része a helyi PASS állításnak

Valódi vállalati Directus-, Google Drive- és Gmail-hitelesítő adatokkal production end-to-end UAT még szükséges. A kód fail-closed módon kezeli a kötelező jóváhagyási és checklist-kapukat, de az éles státusz csak staging pilot után adható.
