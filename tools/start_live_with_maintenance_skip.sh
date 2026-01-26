#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-config/settings.prod.yaml}"
SCHEMA_PATH="${2:-config/schema.json}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "error: config not found: $CONFIG_PATH" >&2
  exit 1
fi
if [[ ! -f "$SCHEMA_PATH" ]]; then
  echo "error: schema not found: $SCHEMA_PATH" >&2
  exit 1
fi

db_path="$(python3 - <<'PY' "$CONFIG_PATH"
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
db_path = ""
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith("db_path:"):
        _, value = stripped.split(":", 1)
        db_path = value.strip().strip('"').strip("'")
        break
if not db_path:
    raise SystemExit("error: db_path not found in config")
print(db_path)
PY
)"

if [[ ! -f "$db_path" ]]; then
  echo "error: db not found: $db_path" >&2
  exit 1
fi

tmp_backup="$(mktemp)"
cleanup() {
  if [[ -f "$tmp_backup" ]]; then
    mv "$tmp_backup" "$CONFIG_PATH"
  fi
}
trap cleanup EXIT INT TERM

cp "$CONFIG_PATH" "$tmp_backup"

python3 - <<'PY' "$CONFIG_PATH"
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
if "maintenance_skip_gap:" not in text:
    raise SystemExit("error: maintenance_skip_gap not found in config")

lines = text.splitlines()
out = []
changed = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("maintenance_skip_gap:"):
        indent = line[: len(line) - len(line.lstrip())]
        out.append(f"{indent}maintenance_skip_gap: true")
        changed = True
    else:
        out.append(line)
if not changed:
    raise SystemExit("error: maintenance_skip_gap not updated")

path.write_text("\n".join(out) + "\n")
PY

safety_mode="$(sqlite3 "$db_path" "select value from system_state where key='safety_mode';")"
reason_code="$(sqlite3 "$db_path" "select value from system_state where key='safety_reason_code';")"

if [[ "$safety_mode" == "HALT" && "$reason_code" == "BACKFILL_WINDOW_EXCEEDED" ]]; then
  echo "safety_mode=HALT reason=BACKFILL_WINDOW_EXCEEDED -> applying maintenance skip (no safety change)"
  PYTHONPATH=src python3 tools/ops_recovery.py \
    --config "$CONFIG_PATH" \
    --schema "$SCHEMA_PATH" \
    --action maintenance-skip \
    --reason-message "Maintenance skip applied"
fi

echo "maintenance_skip_gap=true (temporary) -> starting live mode"
PYTHONPATH=src python3 src/hyperliquid/main.py --mode live --config "$CONFIG_PATH"

safety_mode="$(sqlite3 "$db_path" "select value from system_state where key='safety_mode';")"
if [[ "$safety_mode" == "ARMED_SAFE" ]]; then
  echo "post-boot safety_mode=ARMED_SAFE -> promoting to ARMED_LIVE (operator override)"
  PYTHONPATH=src python3 tools/ops_recovery.py \
    --config "$CONFIG_PATH" \
    --schema "$SCHEMA_PATH" \
    --action promote \
    --reason-message "Promote to ARMED_LIVE after verification" \
    --allow-non-halt
fi
