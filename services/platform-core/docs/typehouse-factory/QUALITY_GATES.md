# Minőségi és kiadási kapuk

Kötelező szerepek: source manifest, GeometryLock, metadata, life situations, tiszta és katalógus alaprajz, pontosan 7680×4320 master, AVIF/WebP reszponzív kimenet, repair log és package manifest.

Egy artefaktum módosítása nullázza a QA-sorozatot. PASS csak teljes hard gate, determinisztikus PASS, szemantikus PASS és legalább a konfigurált pontszám mellett adható. A verifier nem lehet a generátor vagy az API-orchestrátor. A második PASS ugyanahhoz a manifest SHA-256-hoz tartozik; csak ekkor lesz a job `COMPLETED` és a package elérhető.

Forrásjog-, azonosság-, geometria-, méret-, csomagkötés- vagy adatbizonytalanság esetén a kiadás blokkolt.
