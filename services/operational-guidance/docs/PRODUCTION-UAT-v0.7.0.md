# Imperial Intelligence v0.7.0 – production UAT és GO/NO-GO

## 1. Előkészítés

```bash
cp .env.production.example .env
```

Minden `REPLACE_...` értéket ki kell tölteni. A konténerképek csak konkrét verzióval vagy digesttel engedélyezettek; `latest` tiltott.

## 2. Offline production preflight

```bash
python scripts/production_preflight.py \
  --env-file .env \
  --output runtime/production-preflight.json
```

Kötelező eredmény:

- pontosan öt emberi szerepkör és öt egyedi token;
- n8n service-token egyezés;
- idempotency kötelező;
- dokumentációs végpontok letiltva;
- explicit trusted host lista;
- 99/99 folyamat–checklist mapping;
- backup/restore scriptek szintaktikailag érvényesek;
- minden image verzióhoz kötött.

## 3. Online preflight

```bash
python scripts/production_preflight.py \
  --env-file .env \
  --online \
  --require-directus-catalog \
  --output runtime/production-online-preflight.json
```

Ez már valódi PostgreSQL-, Redis-, Directus-, Drive- és Gmail-hozzáférést igényel.

## 4. Mentés és restore drill

```bash
make backup
make backup-verify
make restore-drill
```

Mindhárom lépés PASS nélkül NO-GO.

## 5. Production canary

```bash
python scripts/production_canary.py \
  --env-file .env \
  --base-url https://api.pelda.hu \
  --process-key SAL-001 \
  --output runtime/production-canary.json
```

A canary automatikusan ellenőrzi:

1. liveness és readiness;
2. jogosulatlan kérés elutasítását;
3. katalógusimportot;
4. Process Card generálást;
5. csak ügyvezetővel történő jóváhagyást;
6. munkakörhöz kötött checklist-indítást;
7. azonos idempotency kulcsnál ugyanazt a checklist-példányt;
8. IGEN + evidence + submit + ügyvezetői approval + CLOSED kaput;
9. blocking NEM → HOLD → `can_proceed=false` működést;
10. operációs státusz- és metrics végpontot.

## 6. Automatizált telepítés

```bash
make deploy
```

A telepítő:

- production preflightot futtat;
- ha már van működő adatbázis, mentést készít;
- felépíti a verziózott alkalmazásképet;
- lefuttatja a migrációt;
- readinessre vár;
- teljes canary UAT-ot futtat;
- hiba esetén az előző alkalmazásképre visszaáll.

Az adatbázist hiba esetén sem állítja automatikusan vissza. Destruktív restore csak kézi GO döntéssel történhet.

## 7. GO feltétel

- offline production gate PASS;
- online production preflight PASS;
- backup, verify és restore drill PASS;
- production canary PASS;
- nincs P0/P1 hiba;
- reverse proxy és TLS működik;
- ügyvezető írásos GO döntése rögzítve.

## 8. NO-GO

- hiányzó vagy duplikált munkaköri token;
- service tokennel sikeres approval;
- idempotency nélkül elfogadott production checklist-start;
- 99/99 eltérés;
- HOLD mellett engedélyezett továbblépés;
- readiness 503;
- mentés vagy restore drill hiba;
- `latest` vagy placeholder image;
- nem auditálható kérés.
