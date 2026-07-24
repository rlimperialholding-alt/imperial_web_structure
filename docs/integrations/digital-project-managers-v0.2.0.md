# Digital Project Managers v0.2.0 integration

## Repository fit

The repository had a static, synthetic test platform with no backend dependency
manager, database, migration framework or production authentication. The
service is therefore isolated under `services/digital-project-managers` and
enabled with the optional `digital-pm` Compose profile. Existing portal CI and
the default nginx-only local stack remain unchanged.

The existing project, customer and user collections in
`sites/_portal/data/platform.json` remain canonical. The service reads them
through an adapter and persists only their identifiers in assignments, tasks,
memories and audit events.

## Data and migration

Alembic revision `20260724_0001` creates:

- `digital_project_managers`;
- `project_assignments`;
- `project_memories`;
- `agent_tasks`;
- `approval_requests`;
- `audit_events`.

It seeds Digitális Kálmán, Digitális Máté and Digitális Misi with identical
`standard-r0-r7` authority profiles and deterministic UUIDs. Each manager starts
with one canonical prototype project and a distinct project-memory row.

All mutable business tables have PostgreSQL triggers that write before/after
images and the transaction actor to `audit_events`. Application transactions set
the actor with a transaction-local PostgreSQL setting.

## Security boundary

- API access requires OIDC/JWT scopes and project claims.
- `AUTH_MODE=test` is rejected outside the test environment.
- Credentials are mounted as secret files and ignored by Git.
- External adapters are disabled unless explicitly configured.
- R0-R3 tasks can enter the queue.
- R4-R5 require human approval.
- R6 external commitments and R7 critical actions are blocked and escalated;
  approval cannot automatically execute them.
- Contract modification, liability recognition, performance certification and
  other binding external acts therefore remain human-only.

## External adapters

The adapter registry contains Partner Control, Tender Portal, myImperial and
e-mail interfaces with idempotency headers and bearer credentials loaded from
mounted files. The repository currently contains no safe endpoint or credential
for these systems, so the default adapter implementation refuses writes.

## Queue and operations

Redis/RQ is used because the repository had no existing queue system. The worker
only processes tasks that remain at R0-R3 and are not approval-bound. PostgreSQL,
Redis, migration, API, worker and test containers all run with narrowed
capabilities; the application containers use a non-root user and read-only root
filesystem.
