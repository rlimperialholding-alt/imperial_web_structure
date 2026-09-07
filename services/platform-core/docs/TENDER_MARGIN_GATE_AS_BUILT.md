# TENDER-kapu: 35% direct-margin hard gate és summary-budget allokáció – as-built (Task75/76/77)

Egyetlen kanonikus, tranzakcióba ágyazott, fail-closed kapu a tender-
odaítélés, beszerzési döntés véglegesítés, megrendelés létrehozás/
visszaigazolás, finance-commitment outbox és alvállalkozói szerződés-
átmenetek commitment-mutatóihoz. Nettó alapon számol; nincs admin/owner
override. A kiadás státusza STOP.

## Kanonikus számítás (determinisztikus Decimal)

- Bevétel = `contract_revenue_net + approved_change_revenue_net` > 0.
- Minden sor explicit `cost_class`; besorolatlan sor és indirect csomag-
  gyereksor blokkol (`indirect_child_forbidden`). A tartalékkeret konzervatívan
  direct, amíg jóváhagyott revízió TELJES explicit tartalék-allokációt nem ad.
- Soronkénti várható direct költség = `max(sorkeret, actual + ETC,
  committed_baseline + idempotens lekötések)`; az árva lekötések teljes
  összege konzervatívan a vetületben (soha nem tűnhet el).
- A kapu a KEREKÍTETLEN hányadost veti össze a 35.00 minimummal (34.995 is
  blokk). ÁFA csak a `margin_gate_vat_rules` konfigurációban él, a kapu
  aritmetikáját soha nem módosítja (`vat_applied_in_math: false`).

## Summary-budget roll-down

- Összegző sor kötelező `amount_basis`: `NET_REVENUE_ENVELOPE` → boríték =
  sorbudget × 0.65; `DIRECT_COST_BASELINE` → elvárt bevétel = sorbudget / 0.65.
  Csomag-elköteleződés ≤ boríték (korai blokk); roll-downnál a teljes boríték
  konzervatívan várható direct költség; keresztfinanszírozás tilos.
- Minden csomaghoz jóváhagyott, verziózott, immutable allokációs pillanatkép
  tartozik; az arányok 0.0001-re kvantáltak, pontosan 100.0000 összeget adnak.
  Forrás-precedencia: (1) DETAILED_LINES (terv-lenyomathoz kötött stale-
  detekció), (2) normatábla, (3) historikus tény vagy szállítói bizonyíték;
  minden más ALLOCATION_UNRESOLVED. Alacsony megbízhatóság, részleges
  lefedettség, lejárt/inkonzisztens pillanatkép, nem nulla unallocated (roll-
  down) blokkol. A snapshot-only szakágkódok a csomag-elköteleződésbe és a
  vetületbe is beleszámítanak; a gyerekösszeg-egyeztetés minden forrásnál
  kötelező.

## Idempotencia, TOCTOU és döntés-bizonyíték

- Lekötések: egyedi `(subject_type, subject_id, cost_code)`; újrabeküldés
  csere, kódváltás blokk, kettős számolás kizárt. Tervverzió-jóváhagyáskor a
  lekötések csak akkor kötődnek át, ha a költségkód az új terv direct sorai
  közt szerepel (árva kód → fail-closed az aktiválás ELŐTT).
- A kapu `FOR UPDATE` zárral dolgozik; `verify_plan_unchanged` a commit előtt
  ellenőrzi a verziót/lenyomatot. Az import-jóváhagyás a céltervet szintén
  sorzárral tölti, a draft-ellenőrzést a zár UTÁN, a védett tranzakcióban
  ismétli meg (jóváhagyott terv immutable).
- PASS: pillanatkép + audit a mutáció tranzakciójában. BLOCK: immutable
  bizonyíték független tranzakcióban (FK-mentes plan-hivatkozás), majd
  `MarginGateBlocked`; a hibaüzenet csak aggregált adat.
- Egy döntéshez legfeljebb egy megrendelés: a kódbeli ellenőrzés mellett az
  `uq_ops_procurement_orders_selection_id` kényszer (0073) atomi módon zárja
  ki a konkurens kettőst; az ütközés a kanonikus fail-closed domain hibára
  képeződik (409), a visszagördült mutációt külön tranzakció auditálja.

## Szigorú CSV/XLSX költségvetés-import

1 MB/500 sor/40 oszlop korlát; pontos fejlécsor; képlet (xlsx cella, CSV
'='/@/+ kezdet), makró (vbaProject.bin) és külső hivatkozás elutasítása;
ismétlődő fejléc/kód elutasítása; nettó HUF normalizáció; amount_basis csak
összegző soron, fájlon belül egységes. Preview nem módosít tervet (SHA-256-
tal védett); jóváhagyás csak draft tervre, provenance-nyommal, az import
projektjének egyeznie kell a célterv projektjével (keresztprojekt blokk).

## Enforcement pontok (a mutáció tranzakciójában)

Tender-odaítélés `tender_portal.award_bid` → (tender_bid, bid_id);
PO-előkészítés-jóváhagyás `tender_portal.approve_purchase_order_preparation`
→ ugyanaz a kulcs (kettős számolás kizárt); beszerzési döntés véglegesítés
`procurement.approve_selection`, megrendelés létrehozás/outbox
`procurement.create_order`, visszaigazolás `procurement.confirm_order` →
(procurement_selection, selection_id); alvállalkozói szerződés-átmenetek
`contract_workflow.*` → (contract_workflow, contract_id). Alvállalkozói
szerződéshez a payload `construction_commitment {cost_code, net_huf}` leíró
kötelező; az ügyféloldali szerződések nem commitment-hordozók; ismeretlen
típus `unclassified_contract_type` blokk.

## Séma (20260907_0073)

`finance_budget_imports`, `finance_commitments`, `finance_allocation_snapshots`
+ `_rows`, `margin_gate_decisions` (immutable PASS/BLOCK), `margin_gate_vat_rules`;
oszlopbővítések: `finance_project_plans.content_sha256/provenance_json`,
`finance_project_budget_lines.*` besorolási mezők, `tender_packages.cost_code`,
`procurement_requirements.cost_code`; `uq_ops_procurement_orders_selection_id`
egyedi kényszer (guarddal, batch-rebuild). A downgrade üres tábláknál,
FK-gyerekek a szülők ELŐTT (PostgreSQL RESTRICT-biztos); üzleti soroknál
RuntimeError; a kényszer és az oszlopok adatőrző no-op módon maradnak.

## Jogosultság és felületek

- Import-preview/jóváhagyás, allokáció-rögzítés és `/margin-gate/decisions`:
  a generikus API token mellett a bejelentkezett felhasználó kötelező, és
  csak finance/managing-director/owner/platform-admin szerepkör fogadható el
  (a token ÖNMAGÁBAN nem ad platform-admin-t); az audit a valódi actor
  e-mailjét rögzíti.
- Projekt-scope (Task77): az allokációs API-k a céltervet ELŐSZÖR oldják fel,
  majd fail-closed ellenőrzik az actor projekt-hozzáférését; a döntésnapló
  csak az actor számára elérhető projektek döntéseit adja vissza; az import-
  preview a megadott projekt elérhetőségét ellenőrzi.
- `/margin-gate` csak olvasható döntésnapló (finance/owner/MD/admin).
- Klónozás: a parent_summary_line_id remap két menetben, a TELJES forrás→klón
  térkép után fut (a sorrend nem rontja el a szülő-mutatókat).

## Bizonyító tesztek

`test_tender_margin_gate.py` (határok, validációk, allokációk, bizonyíték,
ÁFA-izoláció, TOCTOU, szivárgásgátlás, arány-pontosság, snapshot-only kódok),
`test_budget_import.py` (CSV/XLSX fail-closed utak), `test_tender_margin_enforcement.py`
(enforcement határok, rollback, outbox-elnyomás, szerepkörök, API-identitás-
kötés), `test_tender_margin_gate_remediation.py` (review-remediációk),
`test_tender_margin_gate_task77.py` (authorization/concurrency Gate7
remediációk), `scripts/verify_tender_margin_gate_migration.py`
(upgrade/downgrade/upgrade bizonyíték). Minden fixture szintetikus.
