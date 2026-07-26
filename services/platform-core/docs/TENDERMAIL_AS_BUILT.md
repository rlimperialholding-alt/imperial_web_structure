# Imperial TenderMail v0.1 – as-built

## Cél

Több száz alvállalkozó és beszállító személyre szabott tendermeghívása úgy, hogy a rendszer védje a feladói reputációt, ne használjon tömeges BCC-t, és minden bounce-, panasz- vagy leiratkozási eseményt azonnal érvényesítsen.

## Megvalósított objektumok

- `MailSendingDomain`
- `MailSuppression`
- `TenderMailCampaign`
- `TenderMailRecipient`
- `TenderMailEvent`

## Küldési kapuk

1. Aktív, külön küldési domain.
2. SPF = pass.
3. DKIM = pass.
4. DMARC = pass.
5. Legalább egy nem tiltott címzett.
6. Kötelező `{{tender_link}}`.
7. Kötelező `{{unsubscribe_url}}`.
8. Kampányóránkénti limit nem haladhatja meg a domainplafont.
9. Éles küldéshez konfigurált provider-adapter.

A provider konfiguráció nem szükséges a kampány üzleti jóváhagyásához és a biztonságos szimulációhoz, de éles küldést blokkol.

## Reputációvédelem

- kisbetűs, validált e-mail-cím;
- kampányon belüli egyedi e-mail-cím;
- globális suppression-lista;
- hard bounce, complaint és unsubscribe automatikus tiltása;
- személyes címzés és változóhelyettesítés;
- dokumentumcsatolmány helyett egyedi tenderlink;
- óránkénti adagolás;
- szolgáltatói események idempotens fogadása.

## Adatforrás

A címzettek kézzel, API-ból vagy az Import Center commitált `partner` és `customer` rekordjaiból adhatók hozzá. A Partner Connect/CRM adatbázist nem másolja át kontroll nélkül: csak aktív, e-mail-címmel rendelkező canonical rekordokat vesz figyelembe, és minden címet összevet a suppression-listával.

## Korlát

A csomag nem tartalmaz éles SES/Mailgun/SendGrid/Postmark vagy más provider-titkot és adaptert. A szimuláció teljes személyre szabott levéltartalmat képez, de nem küld külső e-mailt. Ez szándékos release-kapu, nem hiányzó biztonsági ellenőrzés.
