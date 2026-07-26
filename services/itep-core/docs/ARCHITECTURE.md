# ITEP v0.2 architektúra

## Rétegek

1. **Domain**
   - tiszta üzleti szabályok;
   - státuszállapot-gép;
   - prioritás, késés és eszkaláció;
   - bizonyíték és lezárási invariánsok.

2. **Application**
   - use case szolgáltatások;
   - authorization kapu;
   - repository és outbox portok;
   - Digital Anne enforcement batch.

3. **Infrastructure** – következő verzió
   - Prisma/PostgreSQL repository;
   - Gmail notification adapter;
   - Drive evidence adapter;
   - ütemezett worker;
   - HTTP API.

## Tranzakciós követelmény

A production adapternek egy adatbázis-tranzakcióban kell kezelnie:

- feladatmódosítást;
- audit eseményt;
- notification outbox bejegyzést.

A külső e-mail-küldés csak a committed outboxból történhet. Ezzel elkerülhető,
hogy sikertelen adatbázis-művelet után mégis kimenjen értesítés.

## Idempotencia

Minden automatikus értesítés kulcsa:

`taskId + nextCheckAt + reminderLevel + escalationEvent`

Az adatbázisban ez egyedi, ezért worker újraindítás vagy ismételt futás nem
küldhet duplikált e-mailt.
