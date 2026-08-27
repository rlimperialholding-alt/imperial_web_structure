# Release notes - v0.8.1 staging handoff hotfix

This hotfix does not change the Process Card or Checklist business model. It corrects the remote staging deployment path discovered during developer-handoff preparation.

## Corrected blockers

- staging deployment no longer calls the production-only preflight;
- Directus, PostgreSQL and Redis checks run inside the Compose network via the API container;
- Directus bootstrap and online UAT run inside the API container with the mounted Google secret;
- the Compose project name is stable across releases;
- the Imperial application image receives a release-specific tag so rollback restores the previous binary image;
- third-party images are parameterized and must be pinned by the deployer;
- infrastructure images are pulled separately and the Imperial services are explicitly built;
- rollback performs live preflight and canary before switching the active release pointer.
