# Operational Guidance Engine v0.8.1 — isolated integration

## Purpose

This integration adds the Process Card + Checklist runtime to `rlimperialholding-alt/imperial_web_structure` without changing the existing web platform, nginx routing, root Docker Compose files, or the migration engine.

## Coordination boundary

This branch owns only:

- `services/operational-guidance/**`
- `docs/integrations/operational-guidance-v0.8.1.md`
- `.github/workflows/operational-guidance-ci.yml`

It must not edit work owned by the parallel Codex streams, including:

- `feature/platform-foundation`
- `agent/migration-engine-v1`
- the existing site folders and 12-brand UI
- root nginx and Docker Compose configuration
- shared migration/import code

The CI boundary job rejects a pull request if it contains changes outside the three owned paths.

## Runtime boundary

The service is deliberately self-contained under `services/operational-guidance/`. Its Compose project is `imperial-oge`, so its containers, networks, and volumes do not reuse the web staging project name.

Default local ports are namespaced:

| Service | Address |
|---|---|
| API | `http://127.0.0.1:18080` |
| Directus | `http://127.0.0.1:18055` |
| n8n | `http://127.0.0.1:15678` |
| MinIO API | `http://127.0.0.1:19000` |
| MinIO console | `http://127.0.0.1:19001` |

The existing web staging addresses (`localhost:8080` and `imperial.localhost:8080`) remain untouched.

## Human role constraint

The engine contains exactly five real human roles:

1. Ügyvezető
2. Marketinges
3. Értékesítő
4. Pénzügyes
5. Projektmenedzser

n8n, Directus, CI and other technical identities remain service identities and are not human roles.

## Local validation

```bash
cd services/operational-guidance
cp .env.example .env
python -m pip install -e '.[dev]'
pytest -q tests -k 'not wordpress_fleet'
ruff check app scripts tests

docker compose -p imperial-oge config
docker compose -p imperial-oge up -d --build
curl --fail http://127.0.0.1:18080/live
curl --fail http://127.0.0.1:18080/ready
```

The copied source intentionally excludes the generated WordPress fleet. The existing repository remains the owner of websites, brand previews and site containers. The Operational Guidance service integrates with those components through APIs and approved content records rather than duplicating their source trees.

## Integration manifest integrity

The integration manifest is verified against the exact bytes committed to Git:

```bash
python services/operational-guidance/tools/verify_integration_manifest.py --source head
```

After intentionally changing owned files, stage those files first and regenerate the
manifest from the Git index:

```bash
python services/operational-guidance/tools/verify_integration_manifest.py \
  --source index --refresh
git add services/operational-guidance/INTEGRATION-FILE-MANIFEST.json
python services/operational-guidance/tools/verify_integration_manifest.py --source index
```

The CI manifest-integrity job rejects missing paths, unexpected paths, size changes,
and SHA-256 mismatches.

## Merge sequence

1. Rebase `agent/operational-guidance-v0.8.1` onto the latest `staging` after active Codex PRs settle.
2. Run the path-boundary job and service CI.
3. Open a **draft PR** to `staging`.
4. Do not merge while `feature/platform-foundation` or `agent/migration-engine-v1` changes the same owned paths. Under this layout, overlap should be zero.
5. Connect nginx or the platform UI only in a later dedicated integration PR after the service passes staging UAT.

## Secrets

No real secret is committed. `.env`, service-account JSON, tokens and SSH keys remain ignored. GitHub Actions for this branch performs validation only and does not deploy.
