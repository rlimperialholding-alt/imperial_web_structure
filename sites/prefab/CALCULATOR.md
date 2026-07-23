# Prefab technológiai kalkulátor

## Cél

A kalkulátor egy korai fázisú, tájékoztató döntéstámogató eszköz. A felhasználó
által választott favázas, fémvázas, Ytong, tégla vagy SIP technológiát hasonlítja
össze azonos projektparaméterek mellett Liapor előregyártott agyagbeton
technológiával.

Az eredmény nem kivitelezői ajánlat, statikai szakvélemény vagy hivatalos
ingatlanforgalmi értékbecslés.

## Adatbázis és módszertan

Árbázis: 2026. július.

- Technológiai alapárak: a Google Drive-on található `Kalkuláció oldalakhoz –
  minden weboldal frissített alapárai 2026-07.xlsx` és a Prefab-specifikus
  webkalkulációs árak.
- Időtartamok: az `Ütemtükör – családi ház építési folyamat és
  vállalhatósági modell` cél helyszíni munkanapjai és helyszíni módosítói.
- Ingatlanpiaci kontroll: KSH 2025. IV. negyedéves lakásáradatok, MNB 2026.
  májusi Lakáspiaci jelentés és ingatlan.com újlakás-kínálati adatok.
- Áfa: a felhasználó 5%, 27% vagy nettó megjelenítés közül választ. Az 5%-os
  kulcs jogosultsága minden esetben külön ellenőrzendő.

Az Ártükör tételes munkadíj- és anyagadatai kontrollként szolgálnak; a
kalkulátor nem adja össze őket automatikusan a technológiai kulcsrakész
alapárral.

## Fontos modellkorlátok

- Az alapár minden technológiánál azonos, kulcsrakész készültségi szintre
  normalizált.
- A költségtartomány aszimmetrikus: a korai projektfázisban a felfelé mutató
  költségkockázat nagyobb.
- A teljes projektidő tartalmaz egy tervkészültségtől függő előkészítési
  időtartamot.
- A piaci érték széles régiós benchmark. Pontos település, mikrolokáció,
  telekméret, jogi állapot és összehasonlító tranzakciók nélkül nem lehet
  értékbecslésnek tekinteni.
- A technológiai piaci korrekció kismértékű likviditási/elfogadottsági
  becslés, nem garantált értékkülönbség.
- Az ármodellben nincs telekár, finanszírozás, közműszolgáltatói díj vagy
  hatósági teher. A felhasználó külön telekértéket adhat meg.

## Lead űrlap integráció

Stagingben nincs szerveroldali e-mail-küldés. Az űrlap a kitöltött számítással
egy `mailto:info@prefab.hu` levelet nyit meg. Ez szándékos, mert kliensoldali
JavaScriptből megbízható és biztonságos automatikus e-mail-küldés nem
valósítható meg.

Élesítés előtt a `calculator-assets/config.js` fájlban be kell állítani egy same-origin,
CSRF-védett HTTPS végpontot:

```js
window.PREFAB_CALCULATOR_CONFIG = Object.freeze({
  leadEndpoint: "/api/calculator-lead",
  csrfToken: "szerver-altal-injektalt-token",
  privacyPolicyUrl: "https://prefab.hu/privacy-policy",
  recipientEmail: "info@prefab.hu"
});
```

A végpont JSON törzset kap:

```json
{
  "name": "Teszt Elek",
  "phone": "+36 30 123 4567",
  "email": "teszt@example.hu",
  "consent": true,
  "calculation": "A számítás szöveges összefoglalója",
  "source": "prefab-technology-calculator",
  "priceBase": "2026-07"
}
```

Elvárt szerveroldali védelem:

- CSRF-ellenőrzés és same-origin korlátozás;
- mezőnkénti validáció és fejlécinjektálás elleni védelem;
- IP- és címzettalapú rate limit;
- honeypot vagy CAPTCHA csak igazolt botforgalom esetén;
- naplóban személyes adat minimalizálása;
- az e-mail címzettje szerveroldalon rögzített `info@prefab.hu`, kliensből nem
  felülírható;
- adatkezelési hozzájárulás és időbélyeg auditálható tárolása.

Az éles `prefab.hu` jelenlegi kapcsolatfelvételi végpontja
`/contact/form_contact`, CSRF-tokennel. A kalkulátor éles integrációja ezt a
meglévő szerveroldali folyamatot használhatja adapteren keresztül, de a tokent
nem szabad statikusan a repositoryba tenni.

## Fájlok

- `index.html` – hozzáférhető kalkulátor, összehasonlító táblázat és lead űrlap
- `calculator-assets/calculator.css` – reszponzív Prefab-arculat
- `calculator-assets/calculator.js` – modell, renderelés és űrlapfolyamat
- `calculator-assets/config.js` – staging/production integrációs beállítás
- `calculator-assets/fonts/` – helyben kiszolgált Inter és Bebas Neue WOFF2
  fájlok; külső fontkérés nélkül is megfelel a staging CSP-nek
