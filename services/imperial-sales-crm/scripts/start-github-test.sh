#!/usr/bin/env sh
set -eu

npx wrangler d1 migrations apply DB \
  --local \
  --config wrangler.test.jsonc

exec npx vite --host 0.0.0.0 --port 8787
