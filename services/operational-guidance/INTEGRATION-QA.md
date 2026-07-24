# Operational Guidance v0.8.1 monorepo integration — QA

Date: 2026-07-24
Target repository: `rlimperialholding-alt/imperial_web_structure`
Target base: `staging`
Isolated branch: `agent/operational-guidance-v0.8.1`

## Scope

This is an additive integration. It owns only:

- `services/operational-guidance/**`
- `docs/integrations/operational-guidance-v0.8.1.md`
- `.github/workflows/operational-guidance-ci.yml`

It does not modify root Docker/nginx files, site folders, the platform UI, `feature/platform-foundation`, or `agent/migration-engine-v1`.

## Validation results

- Isolated Python test suite: **57/57 PASS**
- Python AST parse: **88 files PASS**
- JSON parse: **21 files PASS**
- YAML parse: **4 files PASS**
- Operational catalog: **99 processes + 99 checklist templates PASS**
- Internal role boundary: exactly **5** roles PASS
- Owned-path validation: PASS
- Boundary checker positive test: PASS
- Boundary checker negative test: PASS; a root-level foreign change was rejected
- Secret-pattern scan: PASS
- Generated caches and binary handoff documents excluded from the repository patch
- WordPress generated fleet excluded intentionally; the existing web repository remains its owner

## Runtime namespace

- Compose project: `imperial-oge`
- API port: `18080`
- Directus port: `18055`
- n8n port: `15678`
- MinIO ports: `19000` and `19001`
- Existing web staging port `8080` is untouched

## Limitations of this QA run

Docker is not installed in the current execution container, so `docker compose config` and container startup were not run locally. The included path-scoped GitHub Actions workflow performs Compose model validation on GitHub's Ubuntu runner.

The GitHub connector became unavailable during this run, and this isolated container could not resolve `github.com`; therefore no remote branch, commit, push, or pull request was created. The produced patch was independently applied and hash-compared in a local test repository.
