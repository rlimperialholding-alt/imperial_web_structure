# Webhely technikai felmérése

> A dokumentum célja, hogy a webhely stagingbe emeléséhez és későbbi
> üzemeltetéséhez szükséges műszaki információk egy helyen, ellenőrizhető
> formában legyenek. A `[KITÖLTENDŐ]` jelöléseket a felmérés során kell
> tényleges, forrással igazolt adatokra cserélni.

> [!CAUTION]
> Jelszót, tokent, privát kulcsot, connection stringet vagy más secret értéket
> tilos ebbe a fájlba írni. Csak a változó nevét és a jóváhagyott secret store
> hivatkozását dokumentáld.

## 1. Alapadatok és felelősség

| Mező | Érték |
| --- | --- |
| Webhely / márka | `[KITÖLTENDŐ]` |
| Technikai tulajdonos | `[KITÖLTENDŐ — név, csapat, elérhetőség]` |
| Üzleti tulajdonos | `[KITÖLTENDŐ — név, csapat, elérhetőség]` |
| Felmérés dátuma | `[KITÖLTENDŐ — YYYY-MM-DD]` |
| Felmérést végző személy | `[KITÖLTENDŐ]` |
| Dokumentum státusza | `Tervezet / Ellenőrzés alatt / Jóváhagyott` |
| Utolsó ellenőrzés | `[KITÖLTENDŐ — YYYY-MM-DD]` |

## 2. Domainek és hálózati belépési pontok

| Mező | Érték |
| --- | --- |
| Jelenlegi domain | `[KITÖLTENDŐ — teljes URL és kanonikus host]` |
| Staging domain | `[KITÖLTENDŐ — teljes URL; helyi alap: http://<site-slug>.localhost:8080]` |
| Production domain | `[KITÖLTENDŐ — teljes URL]` |
| További domainek / aliasok | `[KITÖLTENDŐ]` |
| DNS szolgáltató és zóna | `[KITÖLTENDŐ]` |
| CDN / WAF | `[KITÖLTENDŐ — szolgáltató és konfiguráció helye]` |
| TLS tanúsítvány kezelése | `[KITÖLTENDŐ — kiállító, megújítás, felelős]` |
| Kötelező redirectek | `[KITÖLTENDŐ — HTTP→HTTPS, www, legacy URL-ek]` |
| Hozzáférési korlátozás | `[KITÖLTENDŐ — VPN, SSO, IP allow-list, basic auth]` |

Ellenőrizendő:

- [ ] A kanonikus domain és minden alias ismert.
- [ ] A staging keresőmotoroktól tiltott és nem publikus tesztadatot használ.
- [ ] A CORS, cookie-domain és callback URL-ek környezetenként különülnek el.
- [ ] A DNS- és TLS-változtatások tulajdonosa jóváhagyta a tervet.

## 3. Technológia

| Mező | Érték |
| --- | --- |
| Technológia | `[KITÖLTENDŐ — statikus oldal, SSR, SPA, CMS, backend stb.]` |
| Framework / CMS | `[KITÖLTENDŐ — név és pontos verzió]` |
| Programozási nyelv | `[KITÖLTENDŐ — nyelv és verzió]` |
| Package manager | `[KITÖLTENDŐ — npm, pnpm, yarn, Composer stb. és verzió]` |
| Függőségi lock fájl | `[KITÖLTENDŐ — fájlnév]` |
| UI / CSS megoldás | `[KITÖLTENDŐ]` |
| Tartalom forrása | `[KITÖLTENDŐ — repository, CMS, adatbázis, API]` |
| Statikus assetek helye | `[KITÖLTENDŐ]` |
| Böngésző-támogatás | `[KITÖLTENDŐ]` |

## 4. Forráskód és verziókezelés

| Mező | Érték |
| --- | --- |
| Forráskód helye | `[KITÖLTENDŐ — repository URL, branch és könyvtár; sablonhely: sites/<site-slug>]` |
| Repository tulajdonosa | `[KITÖLTENDŐ]` |
| Alapértelmezett branch | `[KITÖLTENDŐ]` |
| Staging branch / release flow | `[KITÖLTENDŐ]` |
| Monorepo workspace / projektútvonal | `[KITÖLTENDŐ]` |
| Git submodule / LFS használat | `[KITÖLTENDŐ]` |
| Hozzáférés és CODEOWNERS | `[KITÖLTENDŐ]` |
| Kapcsolódó dokumentáció | `[KITÖLTENDŐ — linkek]` |

## 5. Telepítés, build és teszt

| Mező | Parancs / érték |
| --- | --- |
| Függőségek telepítése | `[KITÖLTENDŐ — reprodukálható, lock fájlt használó parancs]` |
| Build parancs | `[KITÖLTENDŐ]` |
| Fejlesztői parancs | `[KITÖLTENDŐ]` |
| Lint parancs | `[KITÖLTENDŐ]` |
| Unit teszt parancs | `[KITÖLTENDŐ]` |
| Integrációs / E2E teszt | `[KITÖLTENDŐ]` |
| Build output könyvtár | `[KITÖLTENDŐ]` |
| Build idő és erőforrásigény | `[KITÖLTENDŐ]` |
| CI workflow helye | `[KITÖLTENDŐ]` |
| Build során szükséges hálózati elérés | `[KITÖLTENDŐ]` |

Reprodukálhatósági jegyzetek:

```text
[KITÖLTENDŐ — tiszta checkoutból végrehajtott lépések, ismert kivételek,
platformfüggőség és az elvárt sikeres kimenet]
```

## 6. Runtime

| Mező | Érték |
| --- | --- |
| Runtime | `[KITÖLTENDŐ — nginx, Node.js, PHP-FPM, JVM stb.]` |
| Runtime verzió | `[KITÖLTENDŐ — pontos támogatott verzió]` |
| Alap image / operációs rendszer | `[KITÖLTENDŐ — lehetőleg rögzített image referencia]` |
| Indítási parancs | `[KITÖLTENDŐ]` |
| Figyelt port | `[KITÖLTENDŐ]` |
| Health endpoint | `[KITÖLTENDŐ — útvonal és elvárt válasz]` |
| Readiness / liveness feltétel | `[KITÖLTENDŐ]` |
| CPU- és memóriaigény | `[KITÖLTENDŐ — request/limit]` |
| Lokális írható tárhely | `[KITÖLTENDŐ — ideiglenes vagy tartós]` |
| Háttérfolyamat / cron / queue | `[KITÖLTENDŐ]` |
| Graceful shutdown | `[KITÖLTENDŐ]` |

## 7. Környezeti változók és secretek

| Név | Kötelező? | Környezet | Secret? | Forrás / secret store | Leírás és példaformátum |
| --- | --- | --- | --- | --- | --- |
| `[KITÖLTENDŐ]` | `Igen/Nem` | `Build/Runtime/Mindkettő` | `Igen/Nem` | `[KITÖLTENDŐ — érték nélkül]` | `[KITÖLTENDŐ]` |

Környezeti változókkal kapcsolatos ellenőrzések:

- [ ] Minden kötelező változó dokumentált, de secret érték nincs commitolva.
- [ ] A staging és production külön secret scope-ot használ.
- [ ] Ismert az alapérték, validáció és hiányzó érték esetén várható viselkedés.
- [ ] A kulcsok rotációs folyamata és felelőse dokumentált.
- [ ] A kliensoldali buildbe kerülő változók nem tartalmaznak titkot.

## 8. Adatbázis és állapot

| Mező | Érték |
| --- | --- |
| Adatbázis | `[KITÖLTENDŐ — motor, pontos verzió; ha nincs, „Nincs”]` |
| Hosting / cluster | `[KITÖLTENDŐ]` |
| Adatbázis / schema neve | `[KITÖLTENDŐ]` |
| Kapcsolati mód | `[KITÖLTENDŐ — TLS, pool, proxy; connection string nélkül]` |
| ORM / adat-hozzáférési réteg | `[KITÖLTENDŐ]` |
| Migrációs parancs | `[KITÖLTENDŐ]` |
| Seed / tesztadat parancs | `[KITÖLTENDŐ]` |
| Staging adatforrás | `[KITÖLTENDŐ — anonimizált, szintetikus vagy üres]` |
| Személyes / érzékeny adatok | `[KITÖLTENDŐ — kategóriák és kezelés]` |
| Backup és visszaállítás | `[KITÖLTENDŐ — gyakoriság, megőrzés, teszt dátuma]` |
| RPO / RTO | `[KITÖLTENDŐ]` |
| Egyéb tartós tároló | `[KITÖLTENDŐ — object storage, volume, cache]` |

## 9. Külső API-k és integrációk

| Szolgáltatás | Cél | Base URL / endpoint | Auth mód | Sandbox elérhető? | Timeout / retry / rate limit | Tulajdonos |
| --- | --- | --- | --- | --- | --- | --- |
| `[KITÖLTENDŐ]` | `[KITÖLTENDŐ]` | `[KITÖLTENDŐ]` | `[KITÖLTENDŐ — secret nélkül]` | `Igen/Nem` | `[KITÖLTENDŐ]` | `[KITÖLTENDŐ]` |

Integrációs ellenőrzések:

- [ ] A staging minden lehetséges esetben sandbox API-t használ.
- [ ] A webhook callback URL-ek és aláírás-ellenőrzés dokumentált.
- [ ] Az outbound hostok és szükséges tűzfalszabályok listája teljes.
- [ ] A hibakezelés, retry, idempotencia és rate limit viselkedés ismert.
- [ ] Külső szolgáltatáskiesésre van elfogadott fallback.

## 10. Deploy és üzemeltetés

| Mező | Érték |
| --- | --- |
| Deploy cél | `[KITÖLTENDŐ — platform, account/project, service és régió]` |
| Staging deploy cél | `[KITÖLTENDŐ]` |
| Production deploy cél | `[KITÖLTENDŐ]` |
| Artifact típusa | `[KITÖLTENDŐ — container image, statikus bundle stb.]` |
| Artifact registry | `[KITÖLTENDŐ]` |
| Deploy trigger | `[KITÖLTENDŐ — branch, tag, manuális jóváhagyás]` |
| Deploy parancs / workflow | `[KITÖLTENDŐ]` |
| Konfigurációkezelés | `[KITÖLTENDŐ — IaC/repository útvonal]` |
| Migráció sorrendje | `[KITÖLTENDŐ]` |
| Rollback eljárás | `[KITÖLTENDŐ — parancs, előfeltétel és felelős]` |
| Karbantartási ablak | `[KITÖLTENDŐ]` |
| Release jóváhagyó | `[KITÖLTENDŐ]` |

## 11. Megfigyelhetőség és biztonság

| Terület | Megoldás / hely |
| --- | --- |
| Strukturált alkalmazáslog | `[KITÖLTENDŐ]` |
| Hozzáférési és audit log | `[KITÖLTENDŐ]` |
| Metrikák és dashboard | `[KITÖLTENDŐ]` |
| Error tracking | `[KITÖLTENDŐ]` |
| Uptime / szintetikus monitor | `[KITÖLTENDŐ]` |
| Riasztási csatorna és ügyelet | `[KITÖLTENDŐ]` |
| Függőség- és image-szkennelés | `[KITÖLTENDŐ]` |
| Security headerek / CSP | `[KITÖLTENDŐ]` |
| Hitelesítés és jogosultságkezelés | `[KITÖLTENDŐ]` |
| Adatmegőrzés és törlés | `[KITÖLTENDŐ]` |

## 12. Nyitott kérdések és átadási feltételek

| Prioritás | Kérdés / hiány | Felelős | Határidő | Státusz |
| --- | --- | --- | --- | --- |
| `P0/P1/P2/P3` | `[KITÖLTENDŐ]` | `[KITÖLTENDŐ]` | `[KITÖLTENDŐ]` | `Nyitott/Folyamatban/Lezárt` |

Átadási ellenőrzőlista:

- [ ] A jelenlegi domain, staging domain és production domain igazolt.
- [ ] A technológia, forráskód helye, build parancs és runtime reprodukálható.
- [ ] A környezeti változók és secretek kezelése jóváhagyott.
- [ ] Az adatbázis, migráció, backup és staging tesztadat-kezelés ellenőrzött.
- [ ] A külső API-k sandbox/production elválasztása bizonyított.
- [ ] A deploy cél, health check, rollback és monitoring működése tesztelt.
- [ ] Nincs production credential vagy személyes adat a staging környezetben.
- [ ] A technikai és üzleti tulajdonos jóváhagyta a felmérést.
