#!/usr/bin/env bash

# Local Bitvavo read-credential setup.
# This script writes secrets only to local .env.
# It must not be used for broker write permission.

cd "$(dirname "$0")/../.." || exit 1

source scripts/common/secret_input.sh

ENV_FILE=".env"
BACKUP_DIR="logs/env"
PRIVATE_READ_GRANTED="I_UNDERSTAND_THIS_READS_PRIVATE_ACCOUNT_DATA"
WRITE_GRANTED="I_UNDERSTAND_THIS_PLACES_REAL_ORDERS"

mkdir -p "$BACKUP_DIR"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

if grep -q "^SYNTH_BROKER_WRITE_PERMISSION=${WRITE_GRANTED}$" "$ENV_FILE"; then
    echo "FAIL: broker write permission is already granted in .env"
    echo "Remove it before using this read-only setup path."
    exit 1
fi

echo "--- Bitvavo read API setup ---"
echo "Use the Bitvavo API pair named: Synth read"
echo "Bitvavo calls the visible field Name/Key differently than our env naming."
echo

read_visible_value "Bitvavo API name/key field: " BITVAVO_API_KEY_INPUT
read_secret_stars "Bitvavo API secret/signing key: " BITVAVO_API_SECRET_INPUT

if [ -z "$BITVAVO_API_KEY_INPUT" ]; then
    echo "FAIL: API name/key field is empty"
    exit 1
fi

if [ -z "$BITVAVO_API_SECRET_INPUT" ]; then
    echo "FAIL: API secret/signing key is empty"
    exit 1
fi

case "$BITVAVO_API_KEY_INPUT" in
    *[[:space:]]*)
        echo "FAIL: API name/key field contains whitespace; copy only the exact Bitvavo field"
        exit 1
        ;;
esac

case "$BITVAVO_API_SECRET_INPUT" in
    *[[:space:]]*)
        echo "FAIL: API secret/signing key contains whitespace; copy only the exact Bitvavo field"
        exit 1
        ;;
esac

backup="${BACKUP_DIR}/env_before_bitvavo_read_setup_$(date -u +%Y%m%dT%H%M%SZ).txt"
cp "$ENV_FILE" "$backup"
chmod 600 "$backup"

tmp_file="$(mktemp)"
grep -vE '^(BITVAVO_API_KEY|BITVAVO_API_SECRET|SYNTH_BROKER_PRIVATE_READ_PERMISSION)=' "$ENV_FILE" > "$tmp_file" || true

{
    echo ""
    echo "# Bitvavo read-only/private-read setup"
    echo "# Added by scripts/setup/setup_bitvavo_read_env_v1.sh"
    echo "BITVAVO_API_KEY=${BITVAVO_API_KEY_INPUT}"
    echo "BITVAVO_API_SECRET=${BITVAVO_API_SECRET_INPUT}"
    echo "SYNTH_BROKER_PRIVATE_READ_PERMISSION=${PRIVATE_READ_GRANTED}"
} >> "$tmp_file"

mv "$tmp_file" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo
echo "--- written local .env entries, values redacted ---"
print_value_length "BITVAVO_API_KEY" "$BITVAVO_API_KEY_INPUT"
print_value_length "BITVAVO_API_SECRET" "$BITVAVO_API_SECRET_INPUT"

grep -nE '^(BITVAVO_API_KEY|BITVAVO_API_SECRET|SYNTH_BROKER_PRIVATE_READ_PERMISSION|SYNTH_BROKER_WRITE_PERMISSION)=' "$ENV_FILE" \
  | sed -E 's/(=).*/=<redacted>/'

echo
echo "backup=${backup}"
echo "[DONE] Bitvavo read env setup complete"
echo "[DONE] broker write permission unchanged"
