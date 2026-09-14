# Content Factory → Imperial Image Factory

Hatályos: 2026-08-13

## Működés

A platform háttérmunkása minden ciklusban megkeresi azokat a `ContentAsset` rekordokat, amelyek
állapota `VISUAL_PRODUCTION`. Minden tartalomverzióhoz legfeljebb egy tartós Image Factory-kérés
jön létre. Egy batch legfeljebb 100 különálló képfeladatot tartalmaz; minden kép önálló job és
önálló image generation API-kérés marad.

Az alapértelmezett webes profil `1024x1024`, `medium`. A rendszer nem kér high-quality vagy
nagyfelbontású generálást.

Az Image Factory elkészült kimenetét a platform hitelesített belső végpontról tölti le. Import előtt
ellenőrzi a válasz SHA-256 hashét, képformátumát, méretét és a kötelező
`TEST_ONLY_REVIEW_REQUIRED` release-állapotot. A sikeres import után a tartalom
`CREATIVE_DIRECTOR_QA` állapotba kerül; automatikus publikálás nincs.

## Fail-closed szabályok

- Csak `VISUAL_PRODUCTION` állapotú asset küldhető képgenerálásra.
- Több kreatív blokkot tartalmazó assetet előbb külön ContentAsset rekordokra kell bontani.
- Típusterv-, házterv- vagy konkrét termékkreatív nem mehet általános generatív útvonalra; ehhez
  ellenőrzött forrásképet megőrző külön gyártási folyamat szükséges.
- Megváltozott tartalomverzióhoz tartozó kész kép nem importálható.
- Hiányzó vagy eltérő hash, release-állapot, képformátum vagy képméret esetén az import leáll.
- Az Image Factory vagy a hálózat átmeneti hibája tartós, korlátozott visszapróbálkozást kap; egy
  hibás job nem állítja le a teljes batch feldolgozását.

## Üzemeltetési végpontok

A végpontok a platform meglévő API-tokenes védelmét használják.

- `POST /api/content-quality/image-factory/run` – azonnali feldolgozási ciklus.
- `GET /api/content-quality/image-factory/requests` – kérések és állapotuk listája.
- `GET /api/content-quality/image-factory/requests?status=FAILED` – hibás kérések szűrése.

Az Image Factory belső, API-kulccsal védett kimeneti végpontja:

- `GET /api/v1/jobs/{job_id}/assets/{role}`

Engedélyezett szerepek: `master`, `web_hero`, `open_graph`, `square`, `facebook`.

## Kötelező környezeti beállítások

```dotenv
CONTENT_IMAGE_FACTORY_ENABLED=true
CONTENT_IMAGE_FACTORY_HOST=image-factory
CONTENT_IMAGE_FACTORY_PORT=8000
CONTENT_IMAGE_FACTORY_TIMEOUT_SECONDS=30
CONTENT_IMAGE_FACTORY_BATCH_SIZE=100
CONTENT_IMAGE_FACTORY_ASSET_ROOT=/app/runtime/marketing_creatives
IMAGE_FACTORY_API_TOKEN_FILE=/run/secrets/image_factory_api_token
```

A tokent nem szabad forráskódban, naplóban vagy dokumentációban nyers értékkel tárolni.

## Állapotok

- `QUEUED`: helyben sorba állítva.
- `SUBMITTED`: az Image Factory batch és job létrejött.
- `PROCESSING`: az Image Factory dolgozik.
- `IMPORTED`: a hash-ellenőrzött kép bekerült, kreatív igazgatói QA-ra vár.
- `NEEDS_REVIEW`: az Image Factory saját QA-ja emberi ellenőrzést kért.
- `FAILED`: végleges vagy ismétlődő hiba.
- `BLOCKED`: a policy tiltja az általános generálást.
- `STALE`: a tartalomverzió a generálás közben megváltozott.
