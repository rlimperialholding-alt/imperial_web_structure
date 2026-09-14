# MKT-001 — Élő specifikációs review, 1. kör

Review tárgy: Drive master `10sdAJme3LJjs8pnHd7hIjAin979ofCq5_DsqEqn4zqA`, revision `AIroW37Z2kzCHtlWQLw7VfkSYdje626nCM0Ddp0G-XmMH5Pxxi25SHI-5UuvdxMOvj6Qbf-a-5y0fNU8dKzajsCf2I9_Fu-kw-_omlMmttfc` + `specs/MKT-001-live-adaptation-v1.0.md`
Review mód: a szerzői körtől időben elkülönített adversarial pass  
Első verdikt: BLOCKED  
Végső re-review: PASS

## P0

Nincs.

## P1 blokkolók

1. **Immutable evidence vs privacy törlés.** A snapshot immutable, de PII/secret eltávolítás nincs normatív összhangban vele. Titkosított blob crypto-erasure, quarantine és immutable redaction/tombstone record szükséges; downstream readnek fail-closednak kell lennie.
2. **SourceTarget revision/race.** Capture indulás és fetch között target revoke/supersede történhet. Latest-approved target revisiont tranzakciósan kell lockolni/recheckelni, a job policy hash-ével együtt.
3. **ResearchPack review/freeze transition hiányos.** Pontos actor, If-Match, input hash, review outcome és author != approver előfeltételek kellenek; APPROVED után változás nem tarthatja meg a review-t.
4. **Handoff out-of-order/replay.** Újabb pack revision után régi, még időben érvényes revision handoffja nem aktiválhat régi kutatást. Downstream subject-scope monotonic sequence/watermark és supersession recheck kell.
5. **Deny scope listázás.** Globális allow + brand/market deny esetén a query nélküli dashboard nem mutathat tiltott scope-ot; explicit scope vagy effektív allowed-minus-denied SQL filter kell.
6. **Evidence-szint emelés.** A Validation jóváhagyási lifecycle és a findinghez kötött hash nélkül ugyanaz a validation módosított findingot is validálhatna.
7. **Capture parser ellátási lánc.** Parser/model/version hash, sandbox és fertőzött/quarantined input downstream tiltása nem elég normatív.

## P2

- Nagy snapshot bináris storage deduplikáció és retention költségmérés.
- Cluster performance és reprodukálhatóság 100k observation mellett.
- Rövid VOC-idézet maximális karakterszáma piaconként szabályozható.

## Kötelező javítás

A v1.0 fagyasztás csak mind a hét P1 feloldása és konkurencia/negatív tesztek specifikálása után engedélyezett.

## Végső re-review

Mind a hét P1 feloldva: crypto-erasure/tombstone; target parent lock és recheck; explicit pack transition/hash; monotonic handoff watermark; SQL-szintű deny scope; hash-kötött Validation lifecycle; parser digest/quarantine gate. AC-MKT-013–019 tartalmazza a konkurencia és negatív orákulumokat. P0/P1 nem maradt; az élő adaptáció v1.0 fagyasztható.
