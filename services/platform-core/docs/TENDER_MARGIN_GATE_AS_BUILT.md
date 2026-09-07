# TENDER-kapu: 35% direct-margin hard gate és summary-budget allokáció – as-built (Task75/76/77/78)

Egyetlen kanonikus, tranzakcióba ágyazott, fail-closed kapu a tender-odaítélés,
beszerzési döntés véglegesítés, megrendelés létrehozás/visszaigazolás,
finance-commitment outbox és alvállalkozói szerződés-átmenetek commitment-
mutatóihoz. Nettó alapon számol; nincs admin/owner override. A kiadás státusza
STOP.

## Kanonikus számítás

Bevétel = `contract_revenue_net + approved_change_revenue_net` > 0. Minden sor
explicit `cost_class`; besorolatlan sor és indirect csomag-gyereksor blokk. A
tartalékkeret konzervatívan direct, amíg TELJES explicit tartalék-allokáció
nem jön. Soronkénti várható direct = `max(sorkeret, actual + ETC,
committed_baseline + idempotens lekötések)`; az árva lekötések teljes összege
konzervatívan a vetületben. A kapu a KEREKÍTETLEN hányadost veti össze a
35.00 minimummal. ÁFA csak a `margin_gate_vat_rules` konfigurációban él, a
számítást soha nem módosítja (`vat_applied_in_math: false`).

## Summary-budget allokáció

- Összegző sor kötelező `amount_basis`: `NET_REVENUE_ENVELOPE` → boríték =
  sorbudget × 0.65; `DIRECT_COST_BASELINE` → elvárt bevétel = sorbudget / 0.65.
  Csomag-elköteleződés ≤ boríték; roll-downnál a teljes boríték konzervatívan
  várható direct; keresztfinanszírozás tilos. A snapshot-only szakágkódok a
  csomag-elköteleződésbe és a vetületbe is beleszámítanak; a gyerekösszeg-
  egyeztetés minden forrásnál kötelező.
- Jóváhagyott, verziózott, immutable allokációs pillanatkép; arányok 0.0001-re
  kvantáltak, pontosan 100.0000 összeget adnak. Forrás-precedencia: (1)
  DETAILED_LINES (terv-lenyomathoz kötött stale-detekció), (2) normatábla, (3)
  historikus tény / szállítói bizonyíték; minden más ALLOCATION_UNRESOLVED.
  Alacsony megbízhatóság, részleges lefedettség, lejárt/inkonzisztens
  pillanatkép, nem nulla unallocated blokk. Részleges gyerekallokáció nem
  javíthat fedezetet: gyereksoros csomagnál a nem nulla `unallocated_amount`
  fail-closed blokk a mutáció ELŐTT, az esetleges fedetlen boríték-maradék
  konzervatívan egyszer a vetületbe számít.

## Idempotencia, TOCTOU, döntés-bizonyíték

- Lekötések: egyedi `(subject_type, subject_id, cost_code)`; újrabeküldés
  csere, kódváltás blokk, kettős számolás kizárt. Tervverzió-jóváhagyásnál a
  lekötések csak akkor kötődnek át, ha a költségkód az új terv direct sorai
  közt szerepel (árva kód → fail-closed az aktiválás ELŐTT).
- A kapu `FOR UPDATE` zárral dolgozik; `verify_plan_unchanged` a commit előtt
  ellenőrzi a verziót/lenyomatot. Az import-jóváhagyás a céltervet sorzárral
  tölti, a draft-ellenőrzést a zár UTÁN ismétli meg, és az import sor
  újrazárolt állapotát is újraellenőrzi — konkurens jóváhagyásnál az import
  sorai legfeljebb egyszer kerülnek a tervre; jóváhagyott terv immutable.
- PASS: pillanatkép + audit a mutáció tranzakciójában. BLOCK: immutable
  bizonyíték független tranzakcióban (FK-mentes plan-hivatkozás); a hibaüzenet
  csak aggregált adat. Egy döntéshez legfeljebb egy megrendelés: kódbeli
  ellenőrzés + `uq_ops_procurement_orders_selection_id` kényszer (0073) atomi
  zár; az ütközés kanonikus fail-closed domain hibára képeződik (409).

## Import, enforcement, séma

- CSV/XLSX import: 1 MB/500 sor/40 oszlop korlát, pontos fejlécsor; képlet,
  makró (vbaProject.bin) és külső hivatkozás elutasítása; ismétlődő fejléc/kód
  elutasítása; nettó HUF normalizáció; amount_basis csak összegző soron,
  fájlon belül egységes. Preview nem módosít tervet (SHA-256-tal védett);
  jóváhagyás csak draft tervre, provenance-nyommal, az import projektje =
  célterv projektje (keresztprojekt blokk).
- Enforcement pontok: tender-odaítélés (tender_bid, bid_id); PO-előkészítés-
  jóváhagyás (ugyanaz a kulcs, kettős számolás kizárt); beszerzési döntés
  véglegesítés, megrendelés/outbox, visszaigazolás (procurement_selection,
  selection_id); alvállalkozói szerződés-átmenetek (contract_workflow,
  contract_id). Alvállalkozói szerződéshez `construction_commitment {cost_code,
  net_huf}` leíró kötelező; ügyféloldali szerződések nem commitment-hordozók;
  ismeretlen típus blokk.
- Séma (0073): 6 új tábla (importok, commitments, allocation snapshots + rows,
  immutable margin decisions, VAT-rules), oszlopbővítések
  (content_sha256/provenance_json, besorolási mezők, cost_code-ok),
  `uq_ops_procurement_orders_selection_id` (guarddal, batch-rebuild). A
  downgrade üres tábláknál a kényszert a függő táblák ELŐTT dobja el, az
  FK-gyerekek a szülők ELŐTT törlődnek (PostgreSQL RESTRICT-biztos); üzleti
  soroknál a teljes downgrade fail-closed RuntimeError; a re-upgrade guarddal
  idempotens.

## Jogosultság és felületek

Import-preview/jóváhagyás, allokáció-rögzítés és a döntésnapló (mind a
`/margin-gate/decisions`, mind a kötelező `/api/margin-gate/decisions`):
generikus API token mellett a bejelentkezett felhasználó kötelező, és csak
finance/managing-director/owner/platform-admin szerepkör fogadható el (a
token ÖNMAGÁBAN nem ad platform-admin-t); az audit a valódi actor e-mailjét
rögzíti. A jóváhagyás az import projektjének feloldása UTÁN az actor projekt-
hozzáférését is ellenőrzi a mutáció ELŐTT. Projekt-scope: az allokációs API-k
a céltervet ELŐSZÖR oldják fel, majd fail-closed ellenőrzik az actor
hozzáférését; a döntésnapló és a HTML `/margin-gate` dashboard csak az actor
számára elérhető projektek döntéseit adja vissza/rendereli, a körön kívüli
kért projekt 403. Klónozás: a parent_summary_line_id remap két menetben, a
TELJES forrás→klón térkép után fut.

## Bizonyító tesztek

`test_tender_margin_gate.py` (határok, validációk, allokációk, bizonyíték,
ÁFA-izoláció, TOCTOU, szivárgásgátlás, arány-pontosság, snapshot-only kódok,
részleges-allokáció bypass-zárás), `test_budget_import.py` (CSV/XLSX
fail-closed utak), `test_tender_margin_enforcement.py` (enforcement határok,
rollback, outbox-elnyomás, szerepkörök, API-identitás-kötés, dashboard- és
/api-döntésnapló scope), `test_tender_margin_gate_remediation.py`
(review-remediációk; 0073 futás idejű upgrade/downgrade/re-upgrade +
üzleti-sor-elutasítás lánc), `test_tender_margin_gate_task77.py`
(authorization/concurrency Gate7 remediációk, konkurens import-jóváhagyás).
Minden fixture szintetikus.
