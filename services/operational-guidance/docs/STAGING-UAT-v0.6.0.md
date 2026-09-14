# Imperial Intelligence Integration Hub v0.6.0 – Staging UAT és GO/NO-GO

## Cél

A staging kapu azt igazolja, hogy a Process Card Generator, a Checklist Engine és a kapcsolódó integrációs infrastruktúra nem csak helyben működik, hanem kontrolláltan telepíthető is.

## 1. Kötelező előkészítés

1. Másold a `.env.staging.example` fájlt `.env` néven.
2. Cseréld le az összes `REPLACE_...` értéket.
3. Helyezd el a Google service account kulcsát:
   `secrets/google-service-account.json`.
4. Oszd meg a Process Card célmappát a service account e-mail-címével szerkesztőként.
5. Állítsd be a Google Workspace domain-wide delegationt a Gmail-küldéshez.
6. Hozd létre a Directus static tokent a szükséges kollekciójogokkal.

## 2. Offline kapu

```bash
python scripts/staging_preflight.py --env-file .env
```

Ellenőrzi:

- a kötelező titkokat és feature flageket;
- a 99 ProcessID / 99 checklist teljes összerendelését;
- az öt valós szerepkört;
- a runtime mappák írhatóságát;
- a service account JSON szerkezetét.

## 3. Telepítés

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
```

Az indulási sorrend:

1. PostgreSQL;
2. Alembic `upgrade head`;
3. API, worker és beat;
4. MinIO és Directus;
5. n8n csak az API sikeres readiness állapota után.

## 4. Élő preflight

```bash
python scripts/staging_preflight.py \
  --env-file .env \
  --online \
  --require-directus-catalog \
  --output runtime/staging-preflight.json
```

Kötelező PASS:

- adatbázis elérhető;
- Alembic verzió a headen van;
- Redis elérhető;
- Directus health PASS;
- Directusban 99 folyamat és 99 checklist található;
- Drive célmappa írható;
- Gmail delegált felhasználó elérhető.

## 5. Teljes release gate

```bash
python scripts/staging_gate.py \
  --env-file .env \
  --online \
  --output runtime/staging-gate
```

A kapu futtatja:

- a teljes pytest csomagot;
- Python fordíthatósági ellenőrzést;
- Docker Compose szerkezeti validációt;
- Alembic upgrade/downgrade/upgrade ciklust;
- offline/online preflightot;
- mind a 99 Process Card és checklist PDF/PNG generálását és vizsgálatát.

## 6. Funkcionális UAT

Minden folyamatcsaládból legalább egy valós staging esetet kell végigvinni.

Kötelező forgatókönyvek:

1. új vagy módosított folyamatból draft Process Card és checklist készül;
2. a draft csak a `00_JÓVÁHAGYÁSRA_VÁR` ágban jelenik meg;
3. az ügyvezető megkapja a jóváhagyási e-mailt;
4. jóváhagyás után a csomag a `01_ÉRVÉNYES` ágba kerül;
5. a draft átkerül a jóváhagyási archívumba;
6. blocking `NEM` válasz `HOLD` állapotot eredményez;
7. hiányzó bizonyítéknál nincs beküldés;
8. csak `CLOSED` checklist engedi a következő workflow-állapotot;
9. változatlan forrás nem hoz létre új verziót;
10. módosított szabály csak az érintett folyamatot generálja újra;
11. webhook kiesés után a 15 perces safety-net helyreállítja az állapotot;
12. Gmail-hiba után az ötperces retry sikeresen kézbesít.

## 7. GO feltétel

Élesítés csak akkor engedélyezett, ha:

- a staging gate teljes eredménye PASS;
- nincs P0 vagy P1 hiba;
- legalább egy valós folyamat minden családból végigment;
- Drive- és Gmail-jogosultság igazolt;
- backup és restore próba dokumentált;
- az ügyvezető írásban jóváhagyta az élesítést.

## 8. NO-GO feltétel

Automatikus NO-GO:

- 99/99 katalógus eltérés;
- migrációs hiba;
- readiness 503;
- jogosulatlan Drive vagy Gmail kapcsolat;
- draft bekerül az érvényes mappába;
- blocking checklist mellett workflow-továbblépés;
- duplikált Process Card-verzió;
- nem reprodukálható vagy hiányos QA-eredmény.
