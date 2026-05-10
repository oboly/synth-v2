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
echo "Use a Bitvavo API pair with READ/private-account-read permission only."
echo
echo "Important:"
echo "- Do NOT enter the API pair display name, e.g. 'Synth read'."
echo "- Enter the actual generated API key value."
echo "- Then enter the matching API secret/signing key."
echo

read_visible_value "Bitvavo API KEY value, not name/label: " BITVAVO_API_KEY_INPUT
read_secret_stars "Bitvavo API SECRET/signing key: " BITVAVO_API_SECRET_INPUT

if [ -z "$BITVAVO_API_KEY_INPUT" ]; then
    echo "FAIL: API key is empty"
    exit 1
fi

if [ -z "$BITVAVO_API_SECRET_INPUT" ]; then
    echo "FAIL: API secret is empty"
    exit 1
fi

if [ "$BITVAVO_API_KEY_INPUT" = "Synth read" ] || [ "$BITVAVO_API_KEY_INPUT" = "Synth Trade" ]; then
    echo "FAIL: that is the API pair display name, not the API key value"
    exit 1
fi

case "$BITVAVO_API_KEY_INPUT" in
    *[[:space:]]*)
        echo "FAIL: API key contains whitespace; copy only the exact generated key value"
        exit 1
        ;;
esac

case "$BITVAVO_API_SECRET_INPUT" in
    *[[:space:]]*)
        echo "FAIL: API secret contains whitespace; copy only the exact generated secret value"
        exit 1
        ;;
esac

if [ "${#BITVAVO_API_KEY_INPUT}" -lt 20 ]; then
    echo "FAIL: API key looks too short"
    exit 1
fi

if [ "${#BITVAVO_API_SECRET_INPUT}" -lt 20 ]; then
    echo "FAIL: API secret looks too short"
    exit 1
fi

backup="${BACKUP_DIR}/env_before_bitvavo_read_setup_$(date -u +%Y%m%dT%H%M%SZ).txt"
cp "$ENV_FILE" "$backup"
chmod 600 "$backup"

tmp_file="$(mktemp)"
grep -vE '^(BITVAVO_API_KEY|BITVAVO_API_SECRET|SYNTH_BROKER_PRIVATE_READ_PERMISSION)=' "$ENV_FILE" > "$tmp_file" || true

{
    echo ""
    echo "# Bitvavo private read setup"
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
echo "[DONE] Bitvavo private read env setup complete"
echo "[DONE] broker write permission unchanged"
