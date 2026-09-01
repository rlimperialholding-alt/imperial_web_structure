# Directus jóváhagyási és publikálási Flow

A Hub akkor fogad automatikus Directus-eseményt, ha az esemény a `content_items` kollekcióból érkezik, a megadott titok helyes, és az adatbázisból visszaolvasott tartalom aktuális státusza `approved`.

## Beállítás a Directus felületén

1. Hozz létre egy aktív Flow-t `Imperial approved content publish` néven.
2. Trigger: **Event Hook / Action (Non-Blocking)**.
3. Scope: `items.update`.
4. Collection: `content_items`.
5. Operation: **Webhook / Request URL**.
6. Method: `POST`.
7. URL Docker Compose környezetben:

   `http://api:8000/api/v1/publications/webhooks/directus`

8. Header:

   `X-Directus-Secret: <DIRECTUS_WEBHOOK_SECRET értéke>`

9. Request body: a teljes trigger payload, vagy az alábbi objektum:

```json
{
  "event": "{{ $trigger.event }}",
  "collection": "{{ $trigger.collection }}",
  "keys": "{{ $trigger.keys }}",
  "payload": "{{ $trigger.payload }}"
}
```

A Flow minden módosításkor meghívhatja a Hubot. A Hub maga elutasítja vagy figyelmen kívül hagyja a nem `approved` állapotú tartalmat, majd újra lekéri a teljes rekordot Directusból. Így a webhookban érkező részleges vagy manipulált mezők nem válhatnak éles tartalommá.

## Státuszfolyamat

`draft → review → approved → published → archived`

- `approved`: ember által jóváhagyott, publikálható tartalom;
- `published`: az adott publikációs batch minden célweboldalon sikerült;
- `archived`: a `valid_until` lejárt, és minden célweboldal megkapta az unpublish eseményt.

## Időzítés

- `valid_from`: a Hub Celery ETA-feladatként a megadott időpontra ütemezi a publikálást;
- `valid_until`: a Celery Beat 15 percenként ellenőrzi a lejárt tartalmakat, és unpublish eseményt indít.
