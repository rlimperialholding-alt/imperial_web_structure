# Imperial Intelligence v0.7.0 – jogosultsági mátrix

## Alapelv

A rendszer emberi jogosultsági modellje pontosan az öt valós munkakört használja:

1. Ügyvezető
2. Marketinges
3. Értékesítő
4. Pénzügyes
5. Projektmenedzser

A `service` identitás technikai integrációs azonosító, nem hatodik munkakör. A n8n, Directus és más gépi integrációk külön service tokent kapnak. Emberi művelet nem naplózható service identitásként.

## Hitelesítés

Elsődleges fejléc:

```http
Authorization: Bearer <token>
```

Kompatibilitási célból az admin/service végpontok ideiglenesen elfogadják az `X-Imperial-Token` és `X-Admin-Token` fejlécet is. Új integrációban kizárólag Bearer token használható.

## Jogok

| Művelet | Ügyvezető | Folyamat szerinti munkakör | Más munkakör | Service |
|---|---:|---:|---:|---:|
| Process Card katalógusimport | igen | nem | nem | igen |
| Folyamat kézi rögzítése/generálása | igen | nem | nem | igen |
| Process Card jóváhagyása | **igen** | nem | nem | **nem** |
| Checklist-sablon olvasása | igen | igen | igen | igen |
| Checklist-példány indítása | igen | igen | nem | igen |
| Checklist kitöltése/beküldése | igen | igen | nem | igen |
| Checklist-példány jóváhagyása | **igen** | nem | nem | **nem** |
| Gate státusz olvasása | igen | igen | nem | igen |
| Operációs státusz és audit | igen | nem | nem | igen |
| Marketing/ingatlan/szinkron admin API | igen | nem | nem | igen |
| Metrikák | külön metrics token | külön metrics token | külön metrics token | külön metrics token |

## Kötelező biztonsági szabályok

- Mind az öt emberi token legalább 32 karakteres, véletlen és egymástól különböző.
- A service tokenek nem egyezhetnek emberi vagy admin tokennel.
- A n8n konténer `N8N_SERVICE_TOKEN` értéke kötelezően egyezik a `SERVICE_TOKENS_JSON["n8n"]` értékével.
- Jóváhagyást service token nem végezhet.
- A payloadban küldött `created_by`, `answered_by` vagy `approved_by` nem hiteles forrás; a rendszer a tokenből származó aktort rögzíti.
- Minden kérés `X-Request-ID` választ kap, és auditrekord készül.
