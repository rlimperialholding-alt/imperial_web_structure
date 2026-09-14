# Monorepo integration notes

This directory is owned by the `agent/operational-guidance-v0.8.1` workstream.

- It does not replace the repository's root Compose stack.
- It does not own website code or the migration engine.
- It uses Compose project `imperial-oge` and ports 18080/18055/15678/19000/19001.
- It excludes generated WordPress site trees to avoid duplicating the existing 12-brand web structure.
- Run its commands from this directory.

See `../../docs/integrations/operational-guidance-v0.8.1.md`.
