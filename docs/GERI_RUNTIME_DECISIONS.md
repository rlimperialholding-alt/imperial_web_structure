# Léránt Gergely futtatókörnyezeti javaslatainak alkalmazása

Forrás: a „Re: Imperial Intelligence – javasolt szerver- és futtatási
környezet” tárgyú, 2026. július 29-i válasz.

| Javaslat | Megvalósítás / kapu |
|---|---|
| Hetzner, Falkenstein | A kiválasztott Hetzner szerver az `fsn1` régióban fut. |
| Indulásként 4 vCPU / 8 GB RAM | A runtime readiness ezt minimumként ellenőrzi. |
| Docker-alapú, klónozható telepítés | A teljes stack Compose-ból épül; az alkalmazás nem függ kézzel telepített futtatókörnyezettől. |
| Fejlesztés alatt helyi PostgreSQL | A PostgreSQL ugyanazon a szerveren, elkülönített Docker-kötetben fut. Külön adatbázis-szolgáltatás csak későbbi mért terhelés alapján indokolt. |
| S3 helyett később külön fájlszerver | A feltöltések fájlonként és projektenként korlátozottak. Az alap projektkvóta 5 GiB; nagy ügyfélnél külön, 80–200 GiB-ról skálázható fájlszerver szükséges. |
| Google Drive mellett OneDrive-felkészítés | A dokumentumtár forrása Google Drive, OneDrive/SharePoint vagy dedikált fájlszerver lehet. Élő OneDrive-szinkron csak Microsoft tenant- és OAuth-adatokkal kapcsolható be. |
| GitHub verziókezelés és telepítés | A forrás Git-alapú, a telepítési csomag forrás-commitot és ellenőrző összeget tartalmaz. |
| Cloudflare/Zero Trust fejlesztés alatt nem szükséges | A staging portjai kizárólag loopbacken érhetők el, SSH-alagúton tesztelhetők. Nyilvános production eléréshez domain/TLS/SSO vagy Zero Trust külön kapu. |
| Fejlesztői környezettel indulni | A jelenlegi környezet staging/development. A production mód külön, fail-closed konfigurációs kapukat kér. |
| Napi mentés és három hely | A napi mentés és restore-teszt időzített. A backup script két független, felcsatolt replica célra tud ellenőrzött másolatot készíteni; production kapu legalább három helyet kér az elsődlegessel együtt. |
| AI-funkciónként megfelelő modell, költségkontroll | Az OpenRouter/OpenAI provider, rutin- és reasoning-modell, havi költségkeret és kulcsfájl külön konfigurálható. Élő AI-hívás nulla kerettel vagy kulcs nélkül nem indul. |

Staging ellenőrzés:

```bash
bash deploy/remote-test/runtime-readiness.sh staging
```

Production ellenőrzés:

```bash
bash deploy/remote-test/runtime-readiness.sh production
```
