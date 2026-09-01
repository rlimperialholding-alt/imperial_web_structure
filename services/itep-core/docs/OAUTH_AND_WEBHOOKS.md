# OAuth, webhook és connector health v0.9

Az OAuth state egyszer használható és tíz percig érvényes. A callback után a token
kizárólag credential vaultba kerül; az adatbázis csak a connector account metaadatait
tárolja.

A webhook nem tekinthető hiteles üzleti adatnak. Csak szinkronizációs ébresztőjel:
az adapter a provider API-jából tölti le a tényleges Gmail- vagy Calendar-adatot.

Biztonsági szabályok:
- HMAC webhook-aláírás;
- egyszer használható OAuth state;
- token secret vaultban;
- újrahitelesítési állapot;
- connector health endpoint;
- elavult szinkron automatikus észlelése.
