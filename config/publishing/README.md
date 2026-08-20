# Autonomous publishing runtime registry

This directory contains only non-secret brand/channel routing. Runtime credentials live in the server-managed directory mounted at `/run/secrets/publishing` with mode `0600` per file.

Production writes are fail-closed. The kill-switch reference must contain `ALLOW_APPROVED_CANARY` or `ALLOW_APPROVED_WRITES`; staging accepts only `ALLOW_STAGING_WRITES`. A runtime emergency stop is created at `/app/runtime/publishing-kill-switch` after a rollback failure.

NIM routes are enabled only after the real API contract, HMAC header names, exact field map, readback map, endpoints, and secret reference are registered. WordPress requires an application password, never a shared account password. Forum remains `draft_only` unless dated policy evidence and an official API are separately configured.
