from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from src.reporting.run_manual_short_trader_profit_plan_v1 import atomic_text_write


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def _readable_by_nonowner(path: Path) -> bool:
    """Check that group and others have read permission (0o044)."""
    m = _mode(path)
    return bool(m & stat.S_IRGRP) and bool(m & stat.S_IROTH)


# -- Mode checks --

def test_fresh_output_is_0644() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "output.html"
        atomic_text_write("<html>ok</html>", dest)
        assert _mode(dest) == 0o644


def test_repeated_refresh_remains_0644() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "output.html"
        atomic_text_write("first", dest)
        atomic_text_write("second", dest)
        assert _mode(dest) == 0o644


def test_replacing_existing_0600_produces_0644() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "output.html"
        dest.write_text("old content", encoding="utf-8")
        os.chmod(dest, 0o600)
        assert _mode(dest) == 0o600  # pre-condition
        atomic_text_write("new content", dest)
        assert _mode(dest) == 0o644


def test_html_readable_by_nonowner() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "profit-plan.html"
        atomic_text_write("<html>profit plan</html>", dest)
        assert _readable_by_nonowner(dest)


def test_json_readable_by_nonowner() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "profit-plan.json"
        atomic_text_write('{"ok": true}', dest)
        assert _readable_by_nonowner(dest)


# -- Content correctness --

def test_content_is_written_correctly() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "output.html"
        atomic_text_write("<html>hello</html>", dest)
        assert dest.read_text(encoding="utf-8") == "<html>hello</html>"


def test_replace_updates_content() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "output.html"
        atomic_text_write("v1", dest)
        atomic_text_write("v2", dest)
        assert dest.read_text(encoding="utf-8") == "v2"


# -- Atomicity: no temp file left behind on success --

def test_no_tmp_file_left_after_success() -> None:
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "output.html"
        atomic_text_write("content", dest)
        tmp_files = [f for f in Path(d).iterdir() if f.suffix == ".tmp"]
        assert tmp_files == [], f"Temp files left: {tmp_files}"


# -- Atomicity: no temp file left behind on exception --

def test_no_tmp_file_left_when_write_raises() -> None:
    """Simulate a write error by making the directory non-writable temporarily."""
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "sub" / "output.html"
        # dest.parent does not exist → NamedTemporaryFile will fail
        try:
            atomic_text_write("content", dest)
        except Exception:
            pass
        # No .tmp files in d itself
        tmp_files = [f for f in Path(d).iterdir() if f.suffix == ".tmp"]
        assert tmp_files == []


# -- HTML and JSON both correct --

def test_html_and_json_both_0644() -> None:
    with tempfile.TemporaryDirectory() as d:
        html_dest = Path(d) / "profit-plan.html"
        json_dest = Path(d) / "profit-plan.json"
        atomic_text_write("<html/>", html_dest)
        atomic_text_write("{}", json_dest)
        assert _mode(html_dest) == 0o644
        assert _mode(json_dest) == 0o644


# -- Deployment acceptance: mode and readability --

def test_acceptance_mode_0644_verified() -> None:
    """Simulate the deployment acceptance check: file must be mode 0644."""
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "wallet.html"
        atomic_text_write("<html>wallet</html>", dest)
        mode = _mode(dest)
        assert mode == 0o644, f"Expected 0644, got {oct(mode)}"


def test_acceptance_mode_readable_by_www_data_group() -> None:
    """Group read bit must be set so nginx/www-data can serve the file."""
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "profit-plan.html"
        atomic_text_write("<html/>", dest)
        mode = _mode(dest)
        assert mode & stat.S_IRGRP, f"Group read bit not set: {oct(mode)}"


def test_runner_source_uses_atomic_text_write() -> None:
    """The runner must use atomic_text_write, not raw NamedTemporaryFile + os.replace."""
    src = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    assert "atomic_text_write" in src
    assert "os.fchmod" in src
    assert "os.fsync" in src
    # Only one actual NamedTemporaryFile( call — the definition inside atomic_text_write.
    assert src.count("NamedTemporaryFile(") == 1


def test_runner_source_has_no_raw_replace_without_fchmod() -> None:
    """Every os.replace( call must be inside atomic_text_write, not ad-hoc."""
    src = Path("src/reporting/run_manual_short_trader_profit_plan_v1.py").read_text(encoding="utf-8")
    # One os.replace( call — the definition inside atomic_text_write.
    assert src.count("os.replace(") == 1
