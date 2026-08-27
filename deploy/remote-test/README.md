# Imperial Intelligence távoli tesztgép

Ez a csomag egy saját, külön tesztgépre telepíti az Imperial Intelligence teljes
tesztkörnyezetét. A gép lehet az irodában vagy otthon; nem kell hozzá bérelt VPN és
nem kell portot nyitni a routeren.

## Ajánlott gép

- Ubuntu Server 24.04 LTS, 64 bites
- ajánlott: 8 processzormag, 32 GB RAM, legalább 250 GB SSD
- elfogadható minimum: 4 mag, 16 GB RAM, 150 GB szabad SSD
- vezetékes internet és lehetőleg szünetmentes tápegység

A tesztgép ne tartalmazzon napi munkához használt személyes fájlokat. A rendszer
webes portjai csak a gép saját `127.0.0.1` címén nyílnak meg. A távoli böngészős
elérést Cloudflare Tunnel és Cloudflare Access védi.

## A csomag átvitele

A ZIP letölthető a megosztott Drive Archívum
`Imperial Intelligence és Venture Studio – 2026-07-29` mappájából, vagy
átvihető pendrive-on. Letöltés után először ellenőrizzük a beszállításkor megadott
SHA-256 értéket:

```bash
sha256sum imperial-intelligence-remote-test-*.zip
unzip imperial-intelligence-remote-test-*.zip -d imperial-intelligence
cd imperial-intelligence
```

## Szükséges emberi lépések

Két rövid, egyszeri művelethez kell adminisztrátori hozzáférés:

1. A Cloudflare felületén létre kell hozni egy Access alkalmazást, majd egy
   remotely-managed tunnelt. A tunnel tokenjét a telepítő egyszer bekéri.
2. A GitHub repository `Settings > Actions > Runners > New self-hosted runner`
   oldalán ki kell választani a Linux/x64 futtatót. Az ott megjelenő verziót,
   SHA-256 ellenőrző összeget és az egy óráig érvényes regisztrációs tokent a
   telepítő bekéri.

Titkos kulcsot, jelszót vagy tokent ne írjunk e-mailbe, chatbe vagy Gitbe.

## Telepítés

Az alábbi parancsokat az Ubuntu gépen kell futtatni:

```bash
sudo bash deploy/remote-test/install-host.sh
bash deploy/remote-test/prepare-app.sh
bash deploy/remote-test/start.sh
bash deploy/remote-test/healthcheck.sh
```

Az első parancs telepíti a Docker Engine-t és a `cloudflared` programot, majd
létrehozza az `/opt/imperial-intelligence` könyvtárakat. Ezután egyszer ki kell
jelentkezni és vissza kell jelentkezni az Ubuntu felhasználóval. A második parancs
véletlenszerű helyi teszttitkokat készít. A titkok az
`/opt/imperial-intelligence/secrets/remote-test.env` fájlban vannak, `0600`
jogosultsággal, és nem kerülnek a repositoryba.

## Cloudflare elérés

Előbb a Cloudflare Zero Trust felületén hozzuk létre a Self-hosted Access
alkalmazásokat, és csak az engedélyezett e-mail-címeket adjuk hozzá. Legyen
kötelező az egyszer használatos e-mail-kód vagy a fiók MFA-ja. Ezután a tunnel
Public Hostname beállításainál például ezek a belső célok használhatók:

| Külső név | Belső cél | Funkció |
|---|---|---|
| `ii-test.sajatdomain.hu` | `http://localhost:8080` | fő tesztfelület |
| `crm-test.sajatdomain.hu` | `http://localhost:18787` | CRM |
| `itep-test.sajatdomain.hu` | `http://localhost:13000` | ITEP API |
| `hub-test.sajatdomain.hu` | `http://localhost:18080` | Integration Hub |
| `ssh-ii-test.sajatdomain.hu` | `ssh://localhost:22` | védett karbantartás |

Ezután:

```bash
sudo bash deploy/remote-test/configure-cloudflare.sh
```

A tunnel token titok: aki megszerzi, el tudja indítani a tunnelt, ezért csak a
rejtett terminálkérdésbe szabad beilleszteni.

## Távoli karbantartási kapcsolat

A szerverre csak kulcsos SSH-belépés engedélyezett. A jelszavas és a root
belépést a konfiguráló szkript kikapcsolja, az SSH pedig kizárólag a gép saját
`localhost` címén figyel. Emiatt az internet és a helyi hálózat felől sem érhető
el közvetlenül; csak a Cloudflare Tunnel útvonalán.

Először a jelenlegi Windows gépen készítsünk egy külön SSH-kulcsot. Az
`ssh-keygen` kérjen erős jelszót, a `.pub` fájl tartalma nyilvános és
beilleszthető a szerveren:

```powershell
ssh-keygen -t ed25519 -a 100 -f "$env:USERPROFILE\.ssh\imperial-test-admin"
Get-Content "$env:USERPROFILE\.ssh\imperial-test-admin.pub"
```

Ezután a tesztgép fizikai konzolján:

```bash
sudo bash deploy/remote-test/configure-admin-ssh.sh
```

A Cloudflare-ben az SSH hostname-hoz Self-hosted Access alkalmazás kell, csak az
adminisztrátorok e-mail-címeivel és kötelező MFA-val. A Windows SSH-kliens
`ProxyCommand cloudflared access ssh --hostname %h` beállítással csatlakozhat.
A fizikai konzolt csak egy külön ablakban sikeres Cloudflare SSH-próba után
szabad bezárni.

## GitHub runner

```bash
sudo bash deploy/remote-test/configure-runner.sh
```

A runner címkéi: `self-hosted`, `linux`, `x64`, `imperial-test`. A repository
`Remote full-system test` workflow-ja csak kézi `workflow_dispatch` indítással
fut, ezért egy pull request nem tud automatikusan kódot futtatni ezen a saját
gépen.

## Napi használat

```bash
bash deploy/remote-test/start.sh
bash deploy/remote-test/healthcheck.sh
bash deploy/remote-test/backup.sh
bash deploy/remote-test/stop.sh
```

A `stop.sh` nem törli az adatbázisokat és a Docker-köteteket. A biztonsági mentés
nem tartalmaz titkokat. A helyi, jelenlegi számítógépről a Docker/PostgreSQL/Git
csak akkor távolítható el, amikor a távoli gépen:

1. a healthcheck hibátlan;
2. a teljes workflow hibátlan;
3. készült mentés;
4. egy külön visszaállítási próba is sikerült.

Addig a helyi Docker-adatlemezt nem szabad törölni.
