# Forrásjog és forrásazonosság

A feldolgozás előtt kötelező az aktív `owned`, `licensed`, `partner_permission` vagy `open_license` policy. Factory-használathoz a policy tartalmazza az egyedi `grant_id`, tulajdonosi nyilatkozat SHA-256 és oldal-scope SHA-256 mezőket, továbbá domain/útvonal-határt.

Az URL csak HTTPS lehet; userinfo, egyedi port, query, fragment, kódolt/dot/kétperjeles útvonal, privát vagy metadata IP tiltott. A worker DNS-feloldás és kapcsolt peer-IP ellenőrzést is végez. Redirect csak azonos hoston és azonos projektazonossággal engedett. Extradom esetén kizárólag a kanonikus projektoldal-útvonal fogadható.

Jogengedélyt csak valódi, felülvizsgált bizonyíték alapján szabad aktiválni. A rendszer nem következtet engedélyre pusztán nyilvános elérhetőségből.

## Tulajdonosi automatikus domainengedély

A 2026-08-12-i közvetlen tulajdonosi rendelkezés alapján az alábbi alapdomainek és `www` hostjaik automatikusan aktív, domainhez kötött Factory-grantet kapnak:

- `extradom.pl`
- `imperialholding.hu`
- `danishfabrik.hu`
- `prefab.hu`
- `bautica.hu`
- `casa-moderna.hu`
- `timberhaus.hu`

A felületen és API-ban ezekhez a `rights_grant_id: auto` használható, illetve a mező elhagyható. A rendszer minden URL-t a saját `AUTO-RIGHTS-...` grantjéhez köt. Más domainhez továbbra is explicit, jóváhagyott grant szükséges. Az Extradom esetében az automatikus jogengedély nem oldja fel a kanonikus `projekt-domu-...` oldalazonossági szabályt.

Ez kizárólag a forrásjog előkapujára vonatkozik. A forrásadat-, GeometryLock-, render-, 8K-, QA×2- és kiadási kapuk változatlanul kötelezőek.
