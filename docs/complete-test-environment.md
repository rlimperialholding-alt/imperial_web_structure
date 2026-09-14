# Imperial Intelligence teljes helyi tesztkörnyezet

Ez a környezet egy gépen, egymástól elkülönített konténerekben tesztelhetővé
teszi az Imperial Intelligence fő rendszerfelületeit. Nem production
telepítés, nem publikus, és minden HTTP-port csak a helyi gép
`127.0.0.1` címére köt.

## Szolgáltatási határok

| Terület | Kanonikus szolgáltatás | Feladat |
| --- | --- | --- |
| Ügyfél-, projekt-, partner-, dokumentum- és pénzügyi forrásadat | Imperial Sales CRM | A jóváhagyott importált rekordok és forráshivatkozások tartós tára |
| Feladatok, Smart Calendar és eseményorchesztráció | ITEP Core | Idempotens eseményfeldolgozás, prioritás, audit és emberi döntési kapuk |
| Digitális Kálmán, Máté és Misi | Digital Project Managers | Elkülönített projektmemória, R0–R7 kockázati szabályok és audit |
| Modul- és folyamatdemó | Platform Core | A teljes, 47 modulos kattintható rendszer és két szintetikus E2E út |
| Központi integráció | Integration Hub | ITEP-kapcsolat, operációs iránymutatás és readiness ellenőrzés |

Az ITEP és a Digital Project Managers nem duplikálja egymást: az ITEP a közös
feladat- és eseményréteg, míg a Digital PM szolgáltatás a három digitális
projektmenedzser projektmemóriájának és döntési korlátainak tulajdonosa.

## Indítás jóváhagyott helyi CRM-adattal

Az első Docker-build előtt legalább 8 GB szabad hely ajánlott a rendszermeghajtón.
A build-cache később biztonságosan ritkítható a `docker builder prune` paranccsal;
ez nem töröl futó konténert, adatbázis-kötetet vagy CRM-adatot.

PowerShellből:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start-complete-test.ps1 `
  -CrmStatePath 'C:\path\to\approved-crm-state' `
  -CrmWorkspaceId 'imperial-live'
```

A CRM állapotkönyvtár bind mounttal kapcsolódik a konténerhez, ezért a script
nem másolja be és nem commitolja a személyes adatokat. A környezetet csak olyan
helyi állapottal szabad indítani, amelynek használatát külön jóváhagyták.

Adat nélküli, szintetikus próbához hagyd el a két CRM paramétert. Ekkor egy
Docker volume jön létre `imperial-test` workspace-szel.

## Teszt URL-ek

- teljes munkaterület: <http://localhost:8080/workspace/>
- valós adatos CRM: <http://localhost:18787/>
- Digital PM: <http://localhost:8080/digital-project-managers/>
- ITEP readiness: <http://localhost:13000/health/ready>
- Integration Hub readiness: <http://localhost:18080/ready>

## Biztonsági korlátok

- A script futásonként új, véletlen helyi tokeneket generál, és nem írja őket
  fájlba vagy a repositoryba.
- A tartós helyi adatbázis-secreteket meglévő, olvasható tesztfájlból veszi;
  hiányuk esetén a repositoryn kívüli
  `C:\ProgramData\ImperialMigration\runtime-secrets` könyvtárban hozza létre.
- A Compose stack nem tesz közzé internet felé elérhető portot.
- A CRM–ITEP csatlakozó read-only scope-pal indul.
- Külső publikáció, szerződéses, árazási, műszaki és fizetési döntés emberi
  jóváhagyás nélkül blokkolt.
- Production secret, production adatbázis és automatikus production deploy
  nincs ebben a környezetben.
