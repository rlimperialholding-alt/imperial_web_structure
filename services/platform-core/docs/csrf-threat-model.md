# CSRF threat model — platform-core (Task60)

## Architektúra

A platform-core **FastAPI + Jinja2** alkalmazás, **nincs Django-függőség** a
repozitóriumban. A Semgrep `python.django.security.django-no-csrf-token`
szabály Django-template-specifikus (`{% csrf_token %}`), ezért mind a 169
találata (33 template) bizonyított false positive — de csak az alábbi
CSRF-kontrollok tényleges fennállása mellett. Ezt a dokumentum és a
`tests/test_csrf_control_matrix.py` regresszió együtt zárja le.

## Kontrollrétegek

### 1. réteg: `SessionWriteOriginMiddleware` (alkalmazás-globális, fail-closed)

- Implementáció: `app/session_write_guard.py:37` (`class SessionWriteOriginMiddleware`).
- Regisztráció: `app/main.py:1219` (`app.add_middleware(SessionWriteOriginMiddleware)`)
  — egyetlen FastAPI app (`main.py:1180`), minden router bele van include-olva
  (`main.py:1263–1269`), így **minden route** fedett.
- Viselkedés: session-hitelesített kérésnél (`session.user_id` vagy
  `session.partner_access_id`) unsafe methodra (POST/PUT/PATCH/DELETE)
  megköveteli a same-origin bizonyítékot (`Origin`, fallback `Referer`,
  `Host`-hoz illesztve); hiányzó vagy idegen header esetén **403**, a route
  soha nem fut le. API-tokenes/public-tokenes írások nem
  session-hitelesítettek, azokat a saját token-ellenőrzéseik védik
  (a middleware dokumentációja, `session_write_guard.py:38–44`).

### 2. réteg: synchronizer token (a legértékesebb modulokon)

- Központi segédek: `app/main.py:1290–1309` — `_ui_csrf_token`
  (`secrets.token_urlsafe(32)`, sessionbe írva), `_require_ui_csrf`
  (constant-time `hmac.compare_digest`, üres/missing token esetén 403),
  `_operations_csrf`, `_require_calendar_api_csrf` (JSON content-type +
  `x-csrf-token` header).
- Modul-szintű párok (mind 403 fail-closed): `routes/house_studio.py:133/141`,
  `routes/house_designer.py:118/131`, `routes/market_intelligence.py:64/72`
  (form field VAGY `x-csrf-token` + szigorú origin),
  `routes/regulatory_admin.py:45/53`, `routes/typehouse_factory.py:91/99`.

### Tokenizált template-ek (18)

Hidden `csrf_token` inputot renderelnek ÉS a POST handlerjeik token-ellenőrzést
futtatnak: `field_project`, `house_batch_detail`, `house_designer`,
`house_designer_adapters`, `house_designer_detail`,
`house_designer_geometry_controls`, `house_designer_standalone`,
`house_designer_submission_review`, `house_plan_detail`, `house_studio`,
`housevision`, `housevision_detail`, `housevision_typehouse_factory`,
`housevision_upload`, `market_intelligence`, `operations_project`,
`regulatory_admin`, `smart_calendar`.

### Fedettségi mátrix

- 105 template-fájl; 83 tartalmaz POST formot; összesen 441 POST form.
- **Minden** POST form endpoint a middleware alatt fut (app-szintű
  regisztráció) — a `tests/test_csrf_control_matrix.py` végpont- és
  tesztszinten bizonyítja: minden form-action (Jinja-változók probe-azonosítóra
  instantiálva) hitelesített sessionnel + idegen Origin → 403, valamint az üres
  action-ű formok mögötti oldalak is.
- Anonim by design (nincs session, amit CSRF eltéríthetne): `login`,
  `booking_public`, `intent_public`, `reservation_public`, `plancheck_upload`,
  `mail_preferences`, `marketing_consent`, `partner_field_login`,
  `tender_partner`. A token-URL-eken (booking/manage/{token} stb.) a
  capability token az autoritás, nem a session.

## A központi rule-kivétel

Hely: `.github/workflows/imperial-adas-semgrep.yml`, a scan parancsban:

```
--no-rewrite-rule-ids
--exclude-rule python.django.security.django-no-csrf-token.django-no-csrf-token
```

- Egyetlen központi, szűk kivétel: egy rule, a Django-specifikus szabály, a
  Django-mentes FastAPI/Jinja2 alkalmazásra. Nincs inline `nosemgrep` a
  template-ekben, nincs `.semgrepignore`, nincs globális exclude, nincs
  severity-/küszöbcsökkentés, a scan megtartja az `--config auto` +
  `--error` fail-closed kaput.
- Hangosság-feltételek (regresszióval zárolva,
  `tests/test_csrf_control_matrix.py` és
  `tests/test_semgrep_exception_invariants.py`): a middleware regisztrált és
  minden endpointot fed; a kivételhalmaz pontosan a dokumentált halmaz; a
  template-ekben nincs inline CSRF nosemgrep. Ha bármely feltétel megszűnik,
  a kivételt vissza kell vonni.

## Maradék kockázatok (tudatosan vállalt, dokumentált)

- Login CSRF: a login anonim (a middleware pre-session átengedi); a
  login-CSRF (áldozat bejelentkeztetése a támadó fiókjába) ezzel nincs
  origin-ellenőrzéssel védve. Hatás: demo/belső portálon adatszivárgás
  iránya a támadó fiókjába minimális, de a jövőben a login végpontra is
  javasolt Origin-ellenőrzés.
- Az anonim token-URL-ek (booking/manage/{token}) a capability token
  titkosságára építenek; a token kiszivárgása az egyetlen fenyegetés, ezt a
  token entrópiája és a kapcsolat HTTPS-e korlátozza.
