#!/usr/bin/env bash
set -euo pipefail

# ================================
# Synth DB Backup Script
# ================================

# Load env
if [ -f .env ]; then
  set -a
  . .env
  set +a
fi

# Config
BACKUP_DIR="database/backups"
TIMESTAMP=$(date +%F_%H-%M)

DDL_FILE="$BACKUP_DIR/ddl_${TIMESTAMP}.sql"
DATA_FILE="$BACKUP_DIR/data_core_${TIMESTAMP}.sql"

# Optional: cloud sync target (pas aan of leeg laten)
CLOUD_DIR="$HOME/CloudBackups/synth-v2"

# Ensure dirs exist
mkdir -p "$BACKUP_DIR"

echo "==> Starting backup: $TIMESTAMP"

# ================================
# DDL BACKUP (zonder probleem views)
# ================================
echo "==> Dumping DDL..."

mysqldump \
  -h "$DB_HOST" -P "$DB_PORT" \
  -u "$DB_USER" -p"$DB_PASSWORD" \
  --no-data \
  --skip-lock-tables \
  --single-transaction \
  --routines \
  --events \
  --triggers \
  "$DB_NAME" \
> "$DDL_FILE"

# ================================
# CORE DATA BACKUP
# ================================
echo "==> Dumping core data..."

mysqldump \
  -h "$DB_HOST" -P "$DB_PORT" \
  -u "$DB_USER" -p"$DB_PASSWORD" \
  --single-transaction \
  "$DB_NAME" \
  feat_candle \
  signal_engine_state \
  ranking_state \
  selection_state \
  strategy_signal_context \
> "$DATA_FILE"

# ================================
# (OPTIONEEL) CLOUD COPY
# ================================
if [ -d "$CLOUD_DIR" ]; then
  echo "==> Copying to cloud: $CLOUD_DIR"
  cp "$DDL_FILE" "$CLOUD_DIR/"
  cp "$DATA_FILE" "$CLOUD_DIR/"
else
  echo "==> Cloud dir not found, skipping"
fi

# ================================
# DONE
# ================================
echo "==> Backup complete:"
echo "DDL:  $DDL_FILE"
echo "DATA: $DATA_FILE"y

