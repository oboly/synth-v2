# MariaDB Manual Backup Procedure V1

Issue owner: #290

## Purpose

Define the canonical **manual** export procedure for the Synth MariaDB database. This is an operator procedure only: it does not install or activate a timer/service and it does not change schema or runtime behavior.

Canonical runtime database environment is the repo-local `.env`, matching `src/common/db_env_v1.py`. Do not add a second credential source and do not commit `.env`, generated option files, or database dumps.

## Preconditions

Run from a trusted Synth checkout on the intended database host or another already-authorized host with MariaDB client access.

Verify before exporting:

- repository root is the current working directory;
- `.env` exists and contains `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME`;
- the destination directory is outside git, or is otherwise guaranteed ignored;
- sufficient free disk space exists;
- no production mutation is required for the backup.

## Manual full-database export

Use a temporary MariaDB option file so the password is not placed in the command line or written into the dump.

```bash
set -euo pipefail
set -a
. ./.env
set +a

: "${DB_HOST:?missing DB_HOST}"
: "${DB_PORT:?missing DB_PORT}"
: "${DB_USER:?missing DB_USER}"
: "${DB_PASSWORD:?missing DB_PASSWORD}"
: "${DB_NAME:?missing DB_NAME}"

BACKUP_DIR="${HOME}/backups/synth"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/${DB_NAME}_${STAMP}.sql.gz"
CNF="$(mktemp)"
chmod 600 "$CNF"
trap 'rm -f "$CNF"' EXIT

cat >"$CNF" <<EOF
[client]
host=${DB_HOST}
port=${DB_PORT}
user=${DB_USER}
password=${DB_PASSWORD}
EOF

mkdir -p "$BACKUP_DIR"
umask 077
mariadb-dump --defaults-extra-file="$CNF" \
  --single-transaction \
  --routines \
  --events \
  --triggers \
  --databases "$DB_NAME" \
  | gzip -9 >"$OUT"

gzip -t "$OUT"
ls -lh "$OUT"
```

`--single-transaction` provides a consistent snapshot for transactional tables without taking a global write lock. The temporary credentials file is mode `0600` and is removed by the shell trap.

## Verification

A backup is not accepted merely because a file exists.

Minimum verification:

```bash
gzip -t "$OUT"
gzip -dc "$OUT" | head -n 20
```

Confirm that:

- `gzip -t` exits successfully;
- the header identifies a MariaDB dump and the expected database;
- the resulting file size is plausible relative to recent exports;
- no password or other secret appears in the dump filename or operator notes.

A restore test into a disposable database is stronger evidence, but it is a separate explicitly authorized operation. Do not restore into production as part of this procedure.

## Storage and retention

Store exports outside the repository. Preferred local path is `${HOME}/backups/synth/` unless the host has a separately approved backup volume.

Do not commit:

- `.sql` or `.sql.gz` exports;
- temporary option files;
- `.env` or credentials;
- logs containing credential values.

Retention and off-host replication are operational policy decisions and are not automated by this document.

## Existing scripts

Historical scripts such as `scripts/backup_core_weekly.sh` and `scripts/backup_ddl_daily.sh` are not the canonical manual full-database procedure. They load `.env` directly and may serve narrower historical purposes. This document is the operator reference for a manual, secret-safe full Synth export.

## Safety boundary

```text
production_schema_change=0
production_db_write=0
service_activation=0
timer_activation=0
broker_private_calls=0
broker_writes=0
order_submission=0
```
