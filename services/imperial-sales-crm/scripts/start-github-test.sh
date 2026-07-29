#!/usr/bin/env sh
set -eu

./node_modules/.bin/wrangler d1 migrations apply DB \
  --local \
  --config wrangler.test.jsonc

exec ./node_modules/.bin/vite --host 0.0.0.0 --port 8787
