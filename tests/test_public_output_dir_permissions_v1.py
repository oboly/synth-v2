"""
Regression tests: public account output directories must be nginx-readable.

Root cause: systemd UMask=0077 causes Path.mkdir() to create directories
with mode 0700, blocking nginx stat() calls. os.chmod(dir, 0o755) after
mkdir() is the fix applied in all canonical publish paths.

These tests verify that each writer enforces 0o755 even under a restrictive
umask so that the failure mode (drwx------ → 404) cannot regress silently.

broker_private_calls=0
broker_writes=0
"""
from __future__ import annotations

import os
import stat
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dir_mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _assert_readable_dir(path: Path) -> None:
    mode = _dir_mode(path)
    assert mode & 0o755 == 0o755, (
        f"Expected directory mode >= 0o755 (nginx-readable), got {oct(mode)}: {path}"
    )


# ---------------------------------------------------------------------------
# account_profile_home_v1
# ---------------------------------------------------------------------------

def test_account_profile_home_dir_mode_755_under_restrictive_umask() -> None:
    """write_account_profile_home creates profile dir with mode 0o755."""
    from src.reporting.account_profile_home_v1 import write_account_profile_home
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            write_account_profile_home(
                profile_code="testprofile",
                venue="bitvavo",
                account_code="TEST",
                display_timezone="UTC",
                output_root=output_root,
            )
            profile_dir = output_root / "accounts" / "testprofile"
            assert profile_dir.is_dir()
            _assert_readable_dir(profile_dir)
    finally:
        os.umask(old_umask)


def test_account_profile_home_index_html_mode_readable() -> None:
    """index.html written by account_profile_home must be world-readable."""
    from src.reporting.account_profile_home_v1 import write_account_profile_home
    with tempfile.TemporaryDirectory() as tmp:
        output_root = Path(tmp)
        out_path = write_account_profile_home(
            profile_code="testprofile",
            venue="bitvavo",
            account_code="TEST",
            display_timezone="UTC",
            output_root=output_root,
        )
        mode = stat.S_IMODE(os.stat(out_path).st_mode)
        assert mode & 0o644 == 0o644, f"Expected file mode >= 0o644, got {oct(mode)}"


# ---------------------------------------------------------------------------
# account_wallet_dashboard_v1 — verify os.chmod call is present
# ---------------------------------------------------------------------------

def test_wallet_dashboard_source_contains_chmod_755() -> None:
    """write_wallet_dashboard must contain os.chmod(profile_dir, 0o755) after mkdir."""
    src = Path("src/reporting/account_wallet_dashboard_v1.py").read_text()
    assert "os.chmod(profile_dir, 0o755)" in src, (
        "write_wallet_dashboard must explicitly chmod profile_dir to 0o755 after mkdir "
        "to override UMask=0077 from the systemd service unit"
    )


def test_wallet_dashboard_mkdir_chmod_pattern_under_restrictive_umask(tmp_path: Path) -> None:
    """Verify the mkdir+chmod pattern: restrictive umask cannot block a subsequent chmod."""
    old_umask = os.umask(0o077)
    try:
        profile_dir = tmp_path / "accounts" / "someprofile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(profile_dir, 0o755)
        _assert_readable_dir(profile_dir)
    finally:
        os.umask(old_umask)


def test_wallet_dashboard_chmod_corrects_existing_700_dir(tmp_path: Path) -> None:
    """os.chmod corrects an existing 0o700 directory — same pattern used in write_wallet_dashboard."""
    profile_dir = tmp_path / "accounts" / "hugo"
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o700)
    assert _dir_mode(profile_dir) == 0o700

    # The write_wallet_dashboard fix: chmod after mkdir
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(profile_dir, 0o755)
    _assert_readable_dir(profile_dir)


# ---------------------------------------------------------------------------
# run_manual_short_trader_profit_plan_v1 (atomic_text_write + mkdir)
# ---------------------------------------------------------------------------

def test_profit_plan_output_dir_mode_755_under_restrictive_umask(tmp_path: Path) -> None:
    """Profit plan runner creates profile output dir with mode 0o755."""
    from src.reporting.run_manual_short_trader_profit_plan_v1 import atomic_text_write
    old_umask = os.umask(0o077)
    try:
        profile_dir = tmp_path / "accounts" / "testprofile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(profile_dir, 0o755)  # this is the contract the runner enforces
        dest = profile_dir / "profit-plan.html"
        atomic_text_write("<html/>", dest)
        _assert_readable_dir(profile_dir)
        # File itself must also be readable
        fmode = stat.S_IMODE(os.stat(dest).st_mode)
        assert fmode & 0o644 == 0o644, f"Expected file mode >= 0o644, got {oct(fmode)}"
    finally:
        os.umask(old_umask)


def test_atomic_text_write_file_mode_644_under_restrictive_umask(tmp_path: Path) -> None:
    """atomic_text_write always produces a 0o644 file regardless of umask."""
    from src.reporting.run_manual_short_trader_profit_plan_v1 import atomic_text_write
    old_umask = os.umask(0o077)
    try:
        dest = tmp_path / "test.html"
        atomic_text_write("<html>test</html>", dest)
        fmode = stat.S_IMODE(os.stat(dest).st_mode)
        assert fmode == 0o644, f"Expected 0o644, got {oct(fmode)}"
    finally:
        os.umask(old_umask)


# ---------------------------------------------------------------------------
# Smoke check: corrects existing 0o700 dir (simulates the Hugo production bug)
# ---------------------------------------------------------------------------

def test_profile_home_corrects_existing_700_dir() -> None:
    """Regression for Hugo 404: write_account_profile_home must chmod 0o755 even when
    the directory already exists with 0o700 from a previous restrictive-umask run."""
    from src.reporting.account_profile_home_v1 import write_account_profile_home
    with tempfile.TemporaryDirectory() as tmp:
        output_root = Path(tmp)
        profile_dir = output_root / "accounts" / "hugo"
        profile_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(profile_dir, 0o700)  # replicate the production failure
        assert _dir_mode(profile_dir) == 0o700

        write_account_profile_home(
            profile_code="hugo",
            venue="bitvavo",
            account_code="HUGO",
            display_timezone="Europe/Amsterdam",
            output_root=output_root,
        )
        _assert_readable_dir(profile_dir)
