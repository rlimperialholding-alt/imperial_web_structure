# Saját belépés és WhatsApp Business – üzemeltetési útmutató

## Mi készült el

Az Imperial Intelligence belépése nem támaszkodik Microsoft 365-re vagy Entra
ID-ra. Az ITEP Core kezeli:

- az e-mail-címes felhasználókat és a legalább 14 karakteres, `scrypt`
  algoritmussal sózva hashelt jelszavakat;
- a kötelező TOTP kétlépcsős belépést;
- a tíz egyszer használható helyreállító kódot;
- a sikertelen belépések utáni ideiglenes zárolást;
- a titkosított, visszavonható munkamenetet és a CSRF-védelmet;
- a cég-, projekt- és munkaköralapú jogosultságokat, egyedi engedélyezéssel és
  tiltással;
- a rendszeradminisztrátori és ügyvezetői teljes hozzáférést;
- a belépések, megtekintések, módosítások és adminisztratív műveletek
  biztonsági auditját.

A CRM a böngészőtől kapott azonosító fejléceket már nem tekinti hitelesnek.
Minden API-kérésnél a szerveroldali ITEP-munkamenetet ellenőrzi. Ügyfél és
alvállalkozó csak a hozzá rendelt projektek portálját érheti el; a belső CRM
adatait nem.

Felületek:

- `/login` – jelszó, MFA, meghívó aktiválása és helyreállító kód;
- `/admin/access` – cégek, felhasználók, munkakörök, projektek és egyedi
  engedélyek kezelése;
- `/communications/whatsapp` – WhatsApp-beszélgetések, CRM-/projektkapcsolás,
  válasz és jóváhagyás.

## Első adminisztrátor biztonságos létrehozása

Az első fiók csak egyszer, a közvetlen ITEP API-n és a titoktárolóban lévő
`AUTH_BOOTSTRAP_TOKEN` használatával hozható létre:

```powershell
$headers = @{ "X-Bootstrap-Token" = $env:AUTH_BOOTSTRAP_TOKEN }
$body = @{
  email = "admin@imperialholding.hu"
  displayName = "Imperial admin"
  password = "<legalább 14 karakteres egyedi jelszó>"
  organizationId = "imperial-holding"
  organizationName = "Imperial Holding"
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://<itep-api>/v1/auth/bootstrap" `
  -Headers $headers -ContentType "application/json" -Body $body
```

A válaszban szereplő MFA-kulcsot a hitelesítő alkalmazásba kell tenni, majd a
`/login` oldalon befejezni az aktiválást. A bootstrap token ezután
visszavonható. Jelszó, MFA-kulcs és helyreállító kód nem kerülhet GitHubba,
e-mailbe vagy Asanába.

## Kötelező production secretek

Mindegyik legalább 32 karakteres, egymástól független véletlen érték:

- `IDENTITY_SHARED_SECRET`
- `AUTH_TOKEN_PEPPER`
- `AUTH_DATA_ENCRYPTION_KEY`
- `AUTH_BOOTSTRAP_TOKEN` – csak az első admin létrehozásáig
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_DATA_ENCRYPTION_KEY`
- `CONNECTOR_ACCESS_TOKEN_WHATSAPP_LIVE`

További változók:

- `AUTH_COOKIE_SECURE=true`
- `ITEP_BASE_URL` – a CRM szerveréről elérhető belső ITEP API
- `WHATSAPP_CONNECTOR_ID=whatsapp-live`
- `WHATSAPP_PHONE_NUMBER_ID` – a Meta által adott telefonszám-azonosító

## WhatsApp: mi kell még az élő bekötéshez

Az ügyvezető vagy admin személyes telefonszámát nem kötjük az ügyfélkezeléshez.
A jó megoldás egy új, a cég tulajdonában álló SIM/eSIM és külön ügyfélszolgálati
szám. Így a személyes telefon nem csörög, és a hozzáférés munkatársváltáskor is
a cégnél marad.

Szükséges Meta-oldali adatok és lépések:

1. Ellenőrzött Meta Business Portfolio és WhatsApp Business Account.
2. Külön céges telefonszám, amely képes SMS-t vagy hívást fogadni az egyszeri
   Meta-ellenőrzéshez.
3. Meta alkalmazás, benne a WhatsApp termék.
4. A számhoz tartozó `Phone Number ID` és a WhatsApp Business Account ID.
5. Rendszerfelhasználói, tartós hozzáférési token a szükséges
   WhatsApp Business kezelési és üzenetküldési engedélyekkel.
6. Nyilvános HTTPS webhook az ITEP
   `/v1/webhooks/whatsapp` útvonalára, feliratkozva a `messages` eseményre.
7. Az App Secret, verify token és hozzáférési token közvetlen rögzítése a
   titoktárolóba.
8. Bejövő és kimenő tesztüzenet, státusz-visszaigazolás, CRM- és
   projektkapcsolás, majd jóváhagyásos küldési próba.

A személyes számon futó jelenlegi WhatsApp Business alkalmazást csak az új céges
szám sikeres próbája után kell megszüntetni vagy visszaalakítani. A rendszer
hanghívást nem kezel, és nem publikál személyes telefonszámot.

Meta elsődleges dokumentáció:

- <https://developers.facebook.com/docs/whatsapp/cloud-api/get-started>
- <https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks>

## Bevezetési kapuk

Production előtt kötelező:

1. adatbázis-migráció és mentés-visszaállítási próba;
2. első admin + ügyvezető MFA-aktiválás és helyreállítási próba;
3. egy dolgozói, egy alvállalkozói és egy ügyfélfiók hozzáférési tesztje;
4. cégek és projektek közötti adatszivárgási negatív teszt;
5. HTTPS, Secure cookie, külön production kulcsok és kulcsrotáció;
6. auditmegőrzési és incidenskezelési szabály jóváhagyása;
7. dedikált WhatsApp-szám, Meta webhook és üzenetküldési próba;
8. csak ezután valós ügyfélkommunikáció.
