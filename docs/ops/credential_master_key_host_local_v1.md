# Credential master key host-local loading v1 (Issue #625)

## Purpose

Remove manual copy/paste/export/unset handling of the credential encryption master key without weakening encrypted credential storage.

Normal production credential consumers on `gurkdb` load the existing production key from:

```text
/etc/synth/account-credential-master-key
```

The file contains exactly one line in the existing canonical format:

```text
v1:<base64url-encoded-32-byte-key>
```

The key is never stored in git or the database and must never be printed in logs, shell history, CLI arguments, artifacts, or issue/PR text.

## Source precedence

`src/account_provisioning/credential_crypto_v1.py::load_master_key_from_env` keeps its existing callable contract but now resolves sources in this order:

1. explicit `SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY` process environment override;
2. canonical host-local file `/etc/synth/account-credential-master-key`.

An invalid explicit environment override fails closed and never falls through to the file. This preserves a deterministic emergency/test override while preventing a malformed higher-priority source from being silently ignored.

## File safety contract

The host-local file must:

- be a regular file, not a symlink;
- be owner-readable;
- have no world permissions;
- have no group write/execute permissions;
- not be executable;
- contain only the versioned key line;
- remain small and bounded.

Recommended production ownership/mode:

```text
owner=root
group=gurk
mode=0640
```

`0600` is also accepted when the invoking runtime can read it.

## One-time migration from Odroid to gurkdb

The existing production key currently lives in the protected Odroid environment file. Copy the existing value once without printing it and without placing it in a command argument.

### On Odroid

Create a user-private transfer file containing only the existing master-key value:

```bash
umask 077
grep '^SYNTH_ACCOUNT_CREDENTIAL_MASTER_KEY=' \
  /home/theone/.config/synth/web-auth.env \
  | cut -d= -f2- > /tmp/synth-account-credential-master-key.transfer
chmod 600 /tmp/synth-account-credential-master-key.transfer
scp /tmp/synth-account-credential-master-key.transfer gurk@gurkdb:~/synth-account-credential-master-key.transfer
rm -f /tmp/synth-account-credential-master-key.transfer
```

### On gurkdb

Install the transferred value into the canonical protected location and remove the transfer copy:

```bash
sudo install -d -o root -g gurk -m 0750 /etc/synth
sudo install -o root -g gurk -m 0640 \
  ~/synth-account-credential-master-key.transfer \
  /etc/synth/account-credential-master-key
rm -f ~/synth-account-credential-master-key.transfer
```

Never `cat` the file during verification.

## Verification

First validate parsing without displaying key material:

```bash
python - <<'PY'
from src.account_provisioning.credential_crypto_v1 import load_master_key_from_env
version, key = load_master_key_from_env()
print(f"MASTER_KEY_OK=1 VERSION={version} BYTES={len(key)}")
PY
```

Expected:

```text
MASTER_KEY_OK=1 VERSION=v1 BYTES=32
```

Then run the bounded account-5 private-read dry-run from `docs/ops/exact_account_private_read_refresh_v1.md`. Successful credential resolution proves the migrated key decrypts the existing envelope and passes the existing fingerprint check. Do not retire the old protected source until this verification succeeds.

## Safety

This migration and loader change do not:

- rotate or rewrite a credential;
- store plaintext broker credentials;
- grant LIVE authority;
- change decision-gate permission;
- change the kill switch;
- enable/start runtime timers;
- submit an order or perform a broker write.

The bounded account-state verification may perform the already-reviewed private-read calls only after the key has been installed successfully.
