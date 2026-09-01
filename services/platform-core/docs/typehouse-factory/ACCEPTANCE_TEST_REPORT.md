# Átvételi tesztjelentés

Állapot: telepítve és technikailag átvéve 2026-08-12-én.

Automatizált lefedettség:

- többforrásos publikus job-payload elutasítása;
- idempotens egyház-job;
- 30 URL-es sorregisztráció;
- 1000 URL-es tartós sorregisztráció;
- hiányzó jogbizonyíték fail-closed blokkolása;
- azonos manifest két független teljes PASS utáni `COMPLETED`.

Telepítés utáni UAT:

- `platform-core`, `gateway` és `typehouse-worker` fut; az alkalmazás és a gateway healthy;
- Alembic-fej: `20260811_0062`; létrejött mind a hét Factory-tábla;
- hitelesített health API: processing enabled, concurrency 1, QA-pass követelmény 2;
- többforrásos publikus job-kérés: HTTP 422, `SINGLE_HOUSE_REQUIRED`;
- élő egyház-job: HTTP 201, a worker egy poll alatt átvette;
- a szándékosan hiányzó joggrant eredménye: `BLOCKED / RIGHTS_SCOPE_FAIL`.

A 30 valódi forrás teljes pozitív vizuális átvétele, a 7680×4320 renderellenőrzés és a 72 órás 1000-házas tartóssági próba források, explicit jogengedélyek és éles render/vision provider-kimenetek nélkül **nem teljesített és nem állítható teljesítettnek**. A telepítés után a rendszer ezeket nem kerüli meg: `NEEDS_REVIEW`/`BLOCKED` állapotban tartja a jobot.
