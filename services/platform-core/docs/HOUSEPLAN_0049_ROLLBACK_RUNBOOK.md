# HousePlan 0049 fail-safe rollback

The `0049_houseplan_execution` migration is additive and its automatic downgrade is intentionally disabled. The four HousePlan business tables, permission replica and `users.itep_subject_id` can contain canonical, migrated or user-created records; an Alembic downgrade must never discard them.

## Before release

1. Put the House Studio write feature flag into fail-closed maintenance mode.
2. Record the current Alembic revision and application image digest.
3. Create a transactionally consistent database backup with restore logs and SHA-256 evidence.
4. Export row counts and primary-key manifests for `houseplan_sources`, `houseplan_batches`, `houseplan_records`, `houseplan_batch_items`, `house_studio_permission_grants` and the populated `users.itep_subject_id` values.
5. Restore the backup into an isolated database and reconcile every count and manifest before the production migration starts.

## Rollback decision

Application rollback means deploying the previous application image while leaving schema 0049 in place. The previous image must be verified to ignore additive tables/columns. If it cannot, keep writes disabled and deploy a forward compatibility migration. Never run a destructive SQL or Alembic downgrade.

## Data restore

A database restore is permitted only for a full incident recovery and only after preserving a fresh forensic backup of the failed state. Restore the previously verified backup, run Alembic and application smoke checks, then reconcile the manifests and row counts. Any mismatch keeps House Studio writes disabled.

## Release validation

Enable writes only after source-rights quarantine/approval states, signed ITEP permission revisions, batch idempotency records, HousePlan–PlanCheck–HouseBuild foreign keys and audit records have been reconciled. Record operator, timestamps, backup identifier, image digest and evidence hashes in the release log.
