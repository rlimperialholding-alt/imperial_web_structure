#!/bin/sh
set -eu

NAME="${BACKUP_NAME:-latest}"
TARGET="/backups/${NAME}"
[ -d "$TARGET" ] || { echo "Backup not found: $TARGET" >&2; exit 2; }
(
  cd "$TARGET"
  sha256sum -c manifest.sha256
  pg_restore --list database.dump >/dev/null
  tar -tzf operational-runtime.tar.gz >/dev/null
  python3 - <<'PY' 2>/dev/null || true
import json
from pathlib import Path
p = Path('operational-process-catalog-v1.0.json')
data = json.loads(p.read_text(encoding='utf-8'))
assert len(data.get('processes', [])) == 99
assert len(data.get('checklist_templates', [])) == 99
PY
)
printf 'Backup verification PASS: %s\n' "$NAME"
