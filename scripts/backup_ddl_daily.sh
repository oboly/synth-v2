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

BACKUP_DIR="database/backups/ddl"
TIMESTAMP="$(date +%F_%H-%M)"
OUT_FILE="$BACKUP_DIR/ddl_${TIMESTAMP}.sql"

mkdir -p "$BACKUP_DIR"

echo "==> DDL backup: $TIMESTAMP"
echo "Running on: $(hostname)"

mysqldump \
  -h "$DB_HOST" \
  -P "$DB_PORT" \
  -u "$DB_USER" \
  -p"$DB_PASSWORD" \
  --no-data \
  --routines \
  --events \
  --triggers \
  "$DB_NAME" \
> "$OUT_FILE"

echo "==> Stored: $OUT_FILE"

# Keep last 21 days
find "$BACKUP_DIR" -type f -name "ddl_*.sql" -mtime +21 -delete

echo "==> Retention: kept last 21 days"
