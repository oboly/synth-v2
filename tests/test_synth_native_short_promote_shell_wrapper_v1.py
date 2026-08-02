"""Shell-level smoke test for ``scripts/synth_native_short_promote_v1.sh``.

Proves the fix for a real installed-symlink failure: when this script is
invoked through a symlink (as it is once installed at
``/usr/local/bin/synth-native-short-promote``), ``BASH_SOURCE[0]`` resolves
to the symlink path itself, not its target. Deriving ``SCRIPT_DIR`` from the
unresolved symlink path put ``SCRIPT_DIR`` at the symlink's own directory
(e.g. ``/usr/local/bin``) and therefore ``REPO_DIR`` at ``/usr/local``,
so the wrapper could never find the repository venv. The script must resolve
the physical target first (``readlink -f``).

This test creates a real symlink to the checked-in script under a scratch
directory, invokes it through that symlink from an unrelated working
directory, and asserts it correctly locates the canonical repository and its
venv rather than failing with "no usable venv found". It stops at the
cheapest possible failure path (no symbols requested) so it needs no
database and performs no mutation.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "synth_native_short_promote_v1.sh"


def test_invocation_through_symlink_resolves_canonical_repo_and_venv(tmp_path: Path) -> None:
    fake_bin = tmp_path / "usr_local_bin"
    fake_bin.mkdir()
    symlink = fake_bin / "synth-native-short-promote"
    symlink.symlink_to(SCRIPT)

    unrelated_cwd = tmp_path / "elsewhere"
    unrelated_cwd.mkdir()

    completed = subprocess.run(
        [str(symlink)],
        cwd=str(unrelated_cwd),
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )

    # A pre-fix symlink invocation fails inside activate_runtime_venv with
    # "no usable venv found" and exit code 1, because SCRIPT_DIR/REPO_DIR
    # were derived from the symlink's own directory. The fixed script must
    # instead reach the Python wrapper and fail on the cheapest, no-DB path:
    # no symbols requested.
    assert "no usable venv found" not in completed.stderr
    assert completed.returncode == 2, completed.stderr

    doc = json.loads(completed.stdout.strip().splitlines()[-1])
    assert doc["event"] == "FAILED"
    assert doc["reason_code"] == "NO_SYMBOLS_REQUESTED"


def test_script_fails_clearly_when_path_resolution_is_unavailable(tmp_path: Path) -> None:
    """When ``readlink`` itself cannot be found (a stripped-down PATH), the
    script must fail with a clear, explicit message rather than an opaque
    cd/venv error. A dangling symlink cannot be used to exercise this path:
    the OS refuses to exec it at all, before any script logic runs; a
    missing ``readlink`` binary is the realistic way ``SCRIPT_PATH`` ends up
    empty."""
    bare_bin = tmp_path / "bare_bin"
    bare_bin.mkdir()
    (bare_bin / "bash").symlink_to("/usr/bin/bash")

    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": str(bare_bin)},
    )
    assert completed.returncode == 1
    assert "could not resolve physical script path" in completed.stderr
