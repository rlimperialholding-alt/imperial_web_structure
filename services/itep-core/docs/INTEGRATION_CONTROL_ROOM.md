# Integration Control Room v0.1

Az Integration Control Room az Imperial Intelligence élő adaptereinek operációs
vezérlőfelülete és backendje.

## Funkciók

- connector health snapshot;
- healthy / degraded / failed / disconnected / reauth állapot;
- egymást követő hibák számlálása;
- exponenciális retry;
- dead-letter queue;
- Human Anne incidens;
- incidens acknowledge és resolve;
- dead-letter acknowledge;
- dashboard aggregáció;
- connector success/failure eseményfogadás.

## Alapelv

A Control Room nem veszi át a CRM, Finance, Contract Generator vagy más
forrásmodul üzleti logikáját. Kizárólag az adapterek és integrációs folyamatok
üzemeltetési állapotát kezeli.

## Következő kapu

- API bootstrapba való bekötés;
- konkrét Gmail, Calendar, Drive, Billingo, bank és CRM executorok;
- valós Prisma migration;
- admin UI;
- 72 órás staging soak test;
- Human Anne incidens adapter;
- production alerting.
