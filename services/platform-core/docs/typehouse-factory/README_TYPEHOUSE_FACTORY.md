# HouseVision Typehouse Factory v1.0

Forrásvezérelt, fail-closed típusház-feldolgozó az Imperial Intelligence platformon.

## Futási szerződés

- Egy publikus generátorhívás pontosan egy kanonikus forrásoldalt és egy házat jelent.
- A 1–1000 URL-es import csak tartós FIFO-sorelemeket regisztrál.
- A generátor globális konkurenciája v1-ben pontosan 1.
- A jog, forrásazonosság, geometria, 8K master, csomagkötés vagy QA bizonyítatlansága blokkoló eredmény.
- `COMPLETED` kizárólag ugyanazon package manifest két egymást követő, független teljes QA PASS eredménye után adható.

Kezelőfelület: `/housevision/typehouse-factory`. Publikus API-alapútvonalak: `/v1/source-imports` és `/v1/type-house-jobs`.

Az első éles forráscsomag előtt létre kell hozni és külön jóvá kell hagyni a forrásdomainre/útvonalra illeszkedő rights grantet. A telepítés nem hoz létre jogengedélyt és nem jelöl házat publikálhatónak.

Kivétel: a tulajdonos által 2026-08-12-én kifejezetten automatikusan jóváhagyott `extradom.pl`, `imperialholding.hu`, `danishfabrik.hu`, `prefab.hu`, `bautica.hu`, `casa-moderna.hu` és `timberhaus.hu` domainek, valamint `www` hostjaik. Ezeknél a Factory saját, auditált automatikus grantet választ. Ez nem oldja fel a további műszaki és kiadási kapukat.
