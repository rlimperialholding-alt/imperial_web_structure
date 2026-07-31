# Megkerülhetetlen marketingminőségi kapuk v1

## Cél

A publikációs rendszer sem Meta-, sem Google Ads-, sem más külső adapter felé nem
adhat át tartalmat három, egymástól független és hitelesített szakértői döntés nélkül:

1. `MARKETING_QA` – online marketing menedzseri kapu;
2. `DIRECT_RESPONSE_QA` – direct-response copywriter kapu;
3. `CREATIVE_DIRECTOR_QA` – vizuális/kreatív igazgatói kapu.

Az adatbázisban tárolt logikai jelzők önmagukban nem számítanak bizonyítéknak.

## Kikényszerítés

- Mindhárom review külön HMAC-kulccsal készül. A kulcsok nem lehetnek azonosak.
- A marketing- és copywriter-reviewer identitása, modellje és futása is különböző.
- A marketing- és copywriter-jegyzőkönyv az `asset_id`, a változatlan copy SHA-256
  és a generálási futás azonosítójához kötött.
- A vizuális jegyzőkönyv ezen felül a konkrét render SHA-256 értékéhez kötött.
- Jóváhagyáskor minden szakmai dimenzió minimuma 9/10.
- Száraz, generikus, márkaidegen vagy nyitott hibát tartalmazó copy nem kaphat
  `APPROVED` döntést.
- A publikációs függvény minden aláírást és kötést újraellenőriz. Nem bízik meg a
  korábban beállított adatbázis-flagben.
- A publikációs proof tartalmazza a három review azonosítóját, hashét,
  artifact-hashét és a teljes kapumanifeszt hashét.
- Külső adapter csak ebből a publikációs proofból kap outbox üzenetet.
- A worker az outbox feldolgozásakor ismét felépíti az adatbázisból a bundle-t,
  az exportlistát és mindhárom kapubizonyítékot. A módosított vagy kézzel
  létrehozott envelope azonnal `dead_letter`, nem retry.
- A `publication-gate-envelope-v1` adapterszerződés a proofazonosítót
  idempotenciakulcsként, a kapumanifeszt hashét és az explicit `META_ADS` /
  `GOOGLE_ADS` célrendszert is rögzíti.
- A vészleállító `PAUSE_OR_UNPUBLISH` csak `QUARANTINED` állapotú assetnél
  érvényes, és nem engedélyezhet automatikus újrapublikálást.
- Az adatbázis check constraint a `PUBLISHED`, `LIVE_QA` és `QUARANTINED`
  állapotokat a külön copywriter-jóváhagyás nélkül is elutasítja.

## Kötelező sorrend

`COPY_QA → SPECIALIST_QA → FOUR_GATE_QA → … → CREATIVE_DIRECTOR_QA → … → RELEASE_APPROVED → LIVE_QA`

A `SPECIALIST_QA` állapotból csak mindkét külön, hitelesített szövegi kapu után
lehet továbblépni. Elutasítás esetén az asset `BLOCKED`; ugyanaz a tartalomverzió
nem kaphat új, felülíró jóváhagyást.

## Secret-management

Kötelező és egymástól különálló secret:

- `CONTENT_EXPERT_REVIEW_SECRET` – magyar nyelvi szakértő;
- `CONTENT_MARKETING_REVIEW_SECRET` – online marketing menedzser;
- `CONTENT_COPYWRITER_REVIEW_SECRET` – direct-response copywriter;
- `CONTENT_VISUAL_REVIEW_SECRET` – kreatív igazgató.

Éles külső publikációnál mindegyik legalább 32 karakteres, secret fájlból is
betölthető. Értékük nem kerülhet a repositoryba.

## Sikertelen benchmark

Az `imperial-engineering-lead-carousel-v1` 2026-07-30-án copyminőségi okból
elutasított jelölt lett. Technikai layout-ellenőrzése nem jelent szakmai
jóváhagyást, ezért generálási benchmarkként és publikációs referenciaként nem
használható.
