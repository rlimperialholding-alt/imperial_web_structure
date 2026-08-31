# Package-age supply-chain threat model — imperial-sales-crm (Task60)

## Probléma

A Task59 rejected diff a Semgrep `npm-missing-minimum-release-age` szabály
kielégítésére a **nem támogatott** `minimum-release-age=7` kulcsot vette fel a
`.npmrc`-be. Ez a kulcs nem része az npm konfigurációs felületének, egyetlen
npm parancs sem érvényesíti — hatástalan konfiguráció, amiről védelmet
állítani tilos. A Task60 a kulcsot eltávolította (a `.npmrc` a base állapotot
őrzi: `audit=false`, `fund=false`, `update-notifier=false`,
`cache=.sites-runtime/npm-cache`).

## A ténylegesen érvényesülő kontroll

`scripts/check-package-age.mjs` — támogatott, futó, tesztelt 7 napos
package-age küszöb:

- bemenet: `package-lock.json` (lockfileVersion 3) minden registry-ből
  feloldott csomagja — prod, optional, dev és devOptional egyaránt (a
  link/file bejegyzések és a version-metadata nélküli bejegyzések kihagyva);
- CI-default: `includeDev=true`, fail-closed — a dev/devOptional függőségek is
  kötelezően vizsgáltak, mielőtt bármely build/test lépés lefut; a
  `--prod-only` kapcsoló explicit prod-kaput állít (dev/devOptional kihagyás);
- bizonyíték: a registry packument `time` térképe a lockolt verzió
  publikálási időpontjáról;
- fail-closed: bármely verzió fiatalabb a küszöbnél, a publikálási idő nem
  bizonyítható (hiányzó `time` bejegyzés, jövőbeli időpont), a packument nem
  tölthető le vagy a registry nem érhető el → exit 1, a CI job elbukik;
- futás: a Quality workflow `imperial-sales-crm` jobjának dedikált lépése
  (`node scripts/check-package-age.mjs`) minden npm ci után; lokálisan
  `npm run check:package-age`;
- teszt: `tests/package-age-check.test.mjs` (13 teszt, offline, determinisztikus):
  prod/optional/dev/devOptional lefedettség, régi/boundary csomag átmegy, fiatal
  prod- és dev-csomag, hiányzó `time`, hiányzó metadata, jövőbeli publikálási
  idő, HTTP- és hálózati registry-hiba, `--prod-only` és custom küszöb
  fail-closed; a scoped név kódolása ellenőrizve.

## Megőrzött fail-closed kontrollok (nem gyengültek)

- lockfile-integrity: `scripts/install-ci.sh` a lockfile SHA-256-tal, az
  integrity-pinelt vinext tarball preflight-tal, flock-kal és bounded npm
  ci-vel telepít;
- `npm audit --omit=dev --audit-level=high` a Quality jobban (install-time
  audit nélkül, explicit gate-ként);
- a `.npmrc` változatlan a base állapothoz képest (nincs új, nem támogatott
  kulcs).

## A központi rule-kivétel

Hely: `.github/workflows/imperial-adas-semgrep.yml`:

```
--exclude-rule package_managers.npm.npm-missing-minimum-release-age.npm-missing-minimum-release-age
```

- Indoklás: a szabály a nem támogatott `.npmrc` kulcs jelenlétét követeli; a
  fenti futó ellenőrzés erősebb (a kulcs nem is létezne). A kivétel
  hangosság-feltételeit a `services/platform-core/tests/
  test_semgrep_exception_invariants.py` zárolja: ha a
  `check-package-age.mjs` vagy a CI-lépése eltűnik, a kivételt vissza kell
  vonni.
- Nincs blanket suppression: a scan megtartja `--config auto` + `--error`;
  a többi npm/supply-chain szabály változatlanul fut.
