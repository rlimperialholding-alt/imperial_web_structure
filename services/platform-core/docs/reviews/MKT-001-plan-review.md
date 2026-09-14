# MKT-001 — Implementációs terv review

Első verdikt: BLOCKED

## P1 és feloldás

1. **Capture fetch túl korán:** production fetch connector nem lehet MVP-kapu. Feloldás: manual/fixture teljes vertikális slice előbb; public fetch külön OFF flag és security teszt.
2. **Tároló/encryption provider nincs kiválasztva:** feloldás: storage/crypto adapter és lokális tesztprovider; production evidence ingestion OFF valódi KMS/object storage nélkül.
3. **Handoff a meglévő briefbe:** CopyBrief nem pack-aware. Feloldás: additív immutable handoff reference/watermark modell; meglévő brief mezőket nem értelmezzük át.
4. **MCI tiltott side effect:** feloldás: import/dependency allowlist és monkeypatch runtime negatív teszt publication/email/budget függvényekre.
5. **Migráció downgrade:** 0051 guard és runbook, üzleti táblák automatikus dropja nincs.

Végső verdikt: PASS. P0/P1 nincs; WP-MKT-01 indítható a HD 0050 után.

