# Odroid disk containment host fix — 2026-07-25

## Status

```text
host execution: PASS
repository canonicalization: REQUIRED
runtime/broker impact: NONE
```

## Scope

This record captures the host-local repair and successful bounded cleanup for:

```text
/home/theone/.local/libexec/synth/odroid-disk-containment-v1.sh
```

The script is host-local and was not present in the repository at the time of this acceptance. This document therefore does not claim that a canonical repository source or installer has already been corrected.

## Root cause

The helper used this form under the script's fail-closed shell settings:

```bash
mountpoint -q "$path" && abort "candidate_is_mountpoint:${path}"
```

For an ordinary non-mountpoint directory, `mountpoint -q` returns non-zero. During the real host run this caused the script to terminate with `rc=32` while validating the protected native-SHORT snapshot directory, before cleanup started.

The affected invariant was intended to be:

- ordinary real directory: continue;
- symlink: abort;
- mountpoint: abort.

## Host-local correction

The helper was changed to explicit conditional control flow:

```bash
require_directory() {
    local path="$1"
    [[ -d "$path" && ! -L "$path" ]] || abort "not_directory:${path}"
    if mountpoint -q "$path"; then
        abort "candidate_is_mountpoint:${path}"
    fi
}
```

This preserves the mountpoint and symlink protections without treating the expected non-mountpoint result as an execution failure.

Validation after the edit:

```text
bash -n: PASS
owner: theone
mode: 0755
sha256: c4601c9f398bd018139c29dd7e78e96edcaac84868b6c23e58584c3eeb442c2a
```

## Successful bounded execution

Execution timestamp:

```text
2026-07-25T11:49:07Z through 2026-07-25T11:49:09Z
```

Result:

```text
rc=0
planned_reclaim_bytes=678121472
root filesystem use=91% -> 87%
available space=1.3G -> 2.0G
inode use=52% -> 52%
```

Observed cache changes:

```text
/home/theone/.codex:                 804M -> 509M
/home/theone/.local/share/claude:    486M -> 244M
/home/theone/.cache/claude:          8.0K -> 8.0K
systemd journal usage:               181.0M unchanged
```

Protected native-SHORT snapshot target:

```text
/var/www/html/synth/_runtime/native_short_context_snapshot_v1/snapshots/nsctx-v1-389aaddef03ea3e445223620
```

The script reported:

```text
broker_private_calls=0
broker_writes=0
order_submission=0
live_orders=0
decision_gate=none
execution_planner=none
executor=none
```

The repository checkout remained clean after execution.

## Canonicalization requirement

Any future repository source, deployment template, installer, or regeneration path for `odroid-disk-containment-v1.sh` must use explicit conditional handling for expected predicate failures. It must not reintroduce the standalone `mountpoint -q ... && abort ...` form under fail-closed shell execution.

Before installation or replacement, validation must include:

1. `bash -n`;
2. an ordinary-directory fixture that passes `require_directory`;
3. a symlink fixture that fails closed;
4. a mountpoint fixture or isolated test proving mountpoints fail closed;
5. confirmation that `/tmp` and `/var/tmp` are not cleanup targets;
6. checksum, owner, and mode recording;
7. no cleanup execution as part of static validation.

Canonical source or installer work remains separate from this host acceptance and must be reviewed before rollout.
