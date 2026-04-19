#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Load env
if [ -f .env ]; then
  set -a
  . .env
  set +a
fi

: "${DB_HOST:?}"
: "${DB_PORT:?}"
: "${DB_USER:?}"
: "${DB_PASSWORD:?}"
: "${DB_NAME:?}"

BACKUP_DIR="database/backups/core"
TIMESTAMP="$(date +%F_%H-%M)"
OUT_FILE="$BACKUP_DIR/core_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "==> CORE backup: $TIMESTAMP"
echo "Running on: $(hostname)"

mysqldump \
  -h "$DB_HOST" \
  -P "$DB_PORT" \
  -u "$DB_USER" \
  -p"$DB_PASSWORD" \
  --single-transaction \
  "$DB_NAME" \
  feat_candle \
  signal_engine_state \
  ranking_state \
  selection_state \
  strategy_signal_context \
| gzip > "$OUT_FILE"

echo "==> Stored: $OUT_FILE"

# Keep last 3
ls -1t "$BACKUP_DIR"/core_*.sql.gz | tail -n +4 | xargs -r rm -f

echo "==> Retention: kept latest 3"
