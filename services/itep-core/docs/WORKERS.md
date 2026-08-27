# ITEP worker architektúra

## Enforcement worker

Feladata:

- a `nextCheckAt` alapján esedékes nyitott feladatok lekérése;
- reminderLevel emelése;
- P1 háromnapos és hétnapos eszkaláció meghatározása;
- értesítés elhelyezése a tranzakciós outboxban;
- audit esemény írása;
- következő ellenőrzési időpont kiszámítása.

Egy időben csak egy tick futhat egy worker példányban.

## Outbox worker

Feladata:

- esedékes, még nem elküldött üzenetek zárolása;
- `FOR UPDATE SKIP LOCKED` használata több worker esetén;
- Gmail vagy más csatorna adapter meghívása;
- sikeres küldés naplózása;
- exponenciális retry;
- nyolc sikertelen próbálkozás után dead-letter állapot.

## Idempotencia

A kiküldéshez tartozó `idempotencyKey` adatbázisban egyedi. A provider felé
ugyanez az érték külön headerként is elküldhető.

## Biztonság

A Gmail transport nem tárolhat OAuth tokent kódban vagy környezeti fájlban.
A production implementáció titoktárból kérje le a hozzáférést.
