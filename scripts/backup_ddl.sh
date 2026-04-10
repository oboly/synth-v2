#!/bin/bash

set -e

mkdir -p database/backups

mysqldump \
  -h "$DB_HOST" \
  -P "$DB_PORT" \
  -u "$DB_USER" \
  -p \
  --no-data \
  --skip-lock-tables \
  --single-transaction \
  --routines \
  --events \
  --triggers \
  "$DB_NAME" > database/backups/ddl_$(date +%F_%H-%M).sql

echo "DDL backup completed"
