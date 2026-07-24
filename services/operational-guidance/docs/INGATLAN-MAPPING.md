# ingatlan.com adatmegfeleltetés

A konkrét kötelező mezők ingatlantípusonként eltérnek, ezért az éles mappinget az Imperial saját ingatlan-adatmodellje és az ingatlan.com tesztvalidációja alapján kell lezárni.

## Stabil azonosítók

| Imperial mező | ingatlan.com mező | Szabály |
|---|---|---|
| `listing.external_key` | `ownId` | Maximum 15 karakter; létrehozás után ne változzon. |
| `listing.agent_external_key` | `agentId` | Az iroda adminban a referens saját ID-jával egyezzen. |
| `listing.operation` | `listingType` | Létrehozás után nem módosítható. |
| `listing.property_type` | `propertyType` | Létrehozás után nem módosítható. |
| `address.city_code` | `city` | Csak hivatalos ingatlan.com értékkészlet. |
| `project.remote_id` | `projectId` | Létrehozás után nem módosítható. |

## Minimális belső mezők

- saját azonosító;
- hirdetési típus és ingatlantípus;
- ár és pénznem;
- alapterület, telekterület, szobák;
- település, városrész és címmegjelenítési szabály;
- legalább 5 karakteres leírás;
- műszaki állapot, fűtés, komfort és energetikai adatok;
- referens;
- képek saját azonosítóval, sorrenddel, felirattal és típusjelöléssel;
- publikációs státusz és érvényesség.

## Fontos korlátozások

- Az API-s Automata Betöltés jogosultság külön megállapodást igényel.
- A licitek, kiemelések és referens-adminisztráció nem az API-ban kezelendők.
- Az API-ból érkező következő szinkron felülírhatja az admin felületen kézzel módosított adatot.
- Az `listingType`, `propertyType`, `city` és `projectId` mezők nem módosíthatók; hibás érték esetén új `ownId` kell.
- Az új építésű minősítéshez kiegészítő manuális folyamat tartozhat.
- Legfeljebb 30 kép tölthető fel; a képek nem tartalmazhatnak tiltott logót, vízjelet vagy elérhetőséget.
