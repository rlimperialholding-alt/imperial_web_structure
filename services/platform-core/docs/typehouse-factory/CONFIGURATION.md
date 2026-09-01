# Konfiguráció

| Változó | Éles alapérték | Jelentés |
|---|---:|---|
| `TYPEHOUSE_FACTORY_PROCESSING_ENABLED` | `true` | Worker feldolgozás |
| `TYPEHOUSE_FACTORY_CONCURRENCY` | `1` | V1-ben más érték indulási hiba |
| `TYPEHOUSE_FACTORY_WORKER_POLL_SECONDS` | `5` | Poll intervallum |
| `TYPEHOUSE_FACTORY_LEASE_SECONDS` | `300` | Tartós lease |
| `TYPEHOUSE_FACTORY_MAX_RENDER_ATTEMPTS` | `3` | Renderpróba-limit |
| `TYPEHOUSE_FACTORY_MAX_REPAIR_CYCLES` | `2` | Javítási ciklusok |
| `TYPEHOUSE_FACTORY_QA_MIN_SCORE` | `92` | Szemantikus minimum |
| `TYPEHOUSE_FACTORY_REQUIRED_CONSECUTIVE_PASSES` | `2` | V1-ben rögzített |
| `TYPEHOUSE_FACTORY_ASSET_ROOT` | `/app/data/housevision-typehouse-factory` | Tartós artefaktumhely |
| `RENDER_PROVIDER` | `source-only` | Bekötött feldolgozó adapter |
| `OPENAI_IMAGE_MODEL` | `gpt-image-2` | Képi provider célmodellje |
| `OPENAI_VISION_MODEL` | `gpt-5.4-mini` | Szemantikus QA célmodellje |

`source-only` módban a worker jogot és forrást ellenőriz, rögzíti a forrásmanifestet, majd a bizonyítatlan geometriát/renderkimenetet `NEEDS_REVIEW` állapotban hagyja. Nem hamisít kész képi eredményt.
