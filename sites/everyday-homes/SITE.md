# Everyday Homes – szerveres tesztcsomag

## Állapot

- Környezet: elkülönített teszt, keresőmotorok számára tiltva.
- Publikálás: `TILOS`, amíg a tartalmi és vizuális jóváhagyások nem teljesek.
- Kanonikus oldalterv: 66 oldal.
- Ténylegesen kidolgozott oldalak: 66.
- Mind a 66 kanonikus útvonal saját tartalmi oldalt kapott; a teljes csomag továbbra is szerkesztési előnézet, nem éles kiadás.

## Technikai felépítés

- Statikus HTML/CSS/JavaScript csomag.
- Külső CDN, font- vagy képfeloldás nincs; minden runtime-asset helyi.
- A márka assetjei kizárólag az `/site-preview/everyday-homes/assets/` útvonalról töltődnek.
- A route-ok külön könyvtári `index.html` belépési pontot kapnak, hogy az nginx preview útvonalán közvetlenül is HTTP 200 választ adjanak.
- Adatbázis, secret és külső API ebben a tesztcsomagban nincs.

## Márkaalapok

- Vezérmondatok: „Otthon – egyszerűen.” és „Kell egy otthon mindenkinek.”
- Színpaletta: mélykékeszöld `#376C76`, meleg narancs `#F3B563`, zsályazöld `#8EAD96`, törtfehér `#F6F3EA`, sötét szövegszín `#25383C`.
- Piros márkaszín használata tiltott.
- Csak a jóváhagyott Everyday Homes logó és márkajel használható.

## Kötelező minőségi folyamat

A részletes, megkerülhetetlen ellenőrzési rend a [CONTENT-GATES.md](CONTENT-GATES.md) fájlban található. Röviden:

1. igazolt források és márkaspecifikus brief;
2. senior online marketing menedzseri terv;
3. magyar webszövegírói és direct-response ellenőrzés;
4. márka- és keresztmárka-elkülönítési ellenőrzés;
5. kreatív igazgatói, reszponzív és olvashatósági ellenőrzés;
6. jogi, pénzügyi és műszaki tényellenőrzés;
7. hashhez kötött, független PASS eredmények;
8. emberi jóváhagyás a publikálás előtt.

R6–R7 művelet, külső kötelezettségvállalás, szerződésmódosítás, felelősségelismerés vagy teljesítésigazolás nem automatizálható.

## Ellenőrző parancsok

```text
python sites/everyday-homes/qa/materialize_routes.py
python sites/everyday-homes/qa/validate_site.py
python <imperial-skill>/scripts/validate_hungarian_construction_language.py sites/everyday-homes
```

Az egész repository szerkezeti ellenőrzését Linux környezetben kell futtatni:

```text
bash scripts/validate-structure.sh
```

## Szerveres útvonalak

- Host alapú teszt: `http://everyday-homes.localhost:8080/`
- Katalógus-preview: `http://127.0.0.1:8080/site-preview/everyday-homes/`
- Szerverkönyvtár: `/opt/imperial-intelligence/app/sites/everyday-homes`

Az éles domainre történő átirányítás vagy publikálás külön emberi jóváhagyást igényel.
