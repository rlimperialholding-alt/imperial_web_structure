# ITEP v1.0 production hardening

A v1.0 célja, hogy a rendszer ne csak funkcionálisan, hanem üzemeltetési és
biztonsági szempontból is telepíthető legyen.

Fő elemek:
- induláskori környezeti konfigurációvalidáció;
- aláírt identity gateway payload;
- lejárati és clock-skew ellenőrzés;
- idempotens write API-k;
- rate limiting;
- liveness és readiness;
- OpenAPI és Swagger UI;
- audit hash-chain és manipulációészlelés.

A kliens által közvetlenül küldött actor headerek production környezetben nem
tekinthetők hitelesnek. A reverse proxy vagy identity gateway aláírt payloadot
állít elő.
