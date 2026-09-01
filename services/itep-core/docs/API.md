# ITEP REST API v0.3

## Kötelező actor headerek

- `x-actor-id`
- `x-organization-id`
- `x-roles` – vesszővel elválasztott
- `x-permissions` – vesszővel elválasztott

Production környezetben ezeket nem a kliens küldi közvetlenül, hanem a hitelesített
identity gateway állítja elő és írja alá.

## Végpontok

### POST /v1/tasks
Feladat létrehozása.

### GET /v1/tasks/:id
Feladat lekérése jogosultság-ellenőrzéssel.

### POST /v1/tasks/:id/transitions
Státuszváltás.

```json
{ "target": "IN_PROGRESS" }
```

### POST /v1/tasks/:id/evidence
Bizonyíték beadása.

```json
{
  "type": "DOCUMENT",
  "uri": "gdrive://file-id",
  "checksum": "sha256..."
}
```

### POST /internal/enforcement/run
Belső worker végpont. Production környezetben hálózatilag és service identityval
védendő.

## Hibakódok

- 400 VALIDATION_ERROR
- 401 ACTOR_CONTEXT_REQUIRED
- 404 TASK_NOT_FOUND
- 409 INVALID_TRANSITION
- 422 DOMAIN_VALIDATION_ERROR
- 500 INTERNAL_ERROR
