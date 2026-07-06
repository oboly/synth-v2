from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


SCRIPT_PATH = Path("scripts/odroid/run_paper_advice_lifecycle_refresh_once.sh")


def test_wrapper_forwards_log_threshold_overrides(tmp_path: Path) -> None:
    repo_dir = Path.cwd()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture_path = tmp_path / "health_args.json"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "capture = Path(os.environ['FAKE_PYTHON_CAPTURE_PATH'])",
                "capture.write_text(json.dumps(sys.argv[1:]), encoding='utf-8')",
                "if sys.argv[1:3] == ['-m', 'src.operations.run_runtime_disk_log_health_v1']:",
                "    raise SystemExit(1)",
                "raise SystemExit(99)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env.update(
        {
            "VIRTUAL_ENV": str(tmp_path / "venv"),
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_PAPER_ADVICE_LIFECYCLE_LOCK": str(tmp_path / "lock"),
            "SYNTH_DISK_HEALTH_PATH": str(repo_dir),
            "SYNTH_DISK_HEALTH_LOG_PATH": "/var/log/syslog",
            "SYNTH_DISK_HEALTH_LOG_WARN_BYTES": "111",
            "SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES": "222",
            "FAKE_PYTHON_CAPTURE_PATH": str(capture_path),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    args = json.loads(capture_path.read_text(encoding="utf-8"))
    assert result.returncode == 1
    assert args[:2] == ["-m", "src.operations.run_runtime_disk_log_health_v1"]
    assert "--log-path" in args
    assert "/var/log/syslog" in args
    assert "--log-warn-bytes" in args
    assert "111" in args
    assert "--log-critical-bytes" in args
    assert "222" in args


def test_wrapper_passes_explicit_stable_checkpoint_state_path(tmp_path: Path) -> None:
    repo_dir = Path.cwd()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    capture_path = tmp_path / "capture.json"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import json",
                "import os",
                "import sys",
                "from pathlib import Path",
                "capture = Path(os.environ['FAKE_PYTHON_CAPTURE_PATH'])",
                "args = sys.argv[1:]",
                "if args[:2] == ['-m', 'src.operations.run_runtime_disk_log_health_v1']:",
                "    raise SystemExit(0)",
                "if args[:2] == ['-m', 'src.etl.bitvavo.run_candles_etl']:",
                "    capture.write_text(json.dumps(args), encoding='utf-8')",
                "    raise SystemExit(0)",
                "if args and args[0] == '-':",
                "    if len(args) == 2:",
                "        print('2026-07-01T00:00:00+00:00 2026-07-01T06:00:00+00:00')",
                "    raise SystemExit(0)",
                "raise SystemExit(0)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env.update(
        {
            "VIRTUAL_ENV": str(tmp_path / "venv"),
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_PAPER_ADVICE_LIFECYCLE_LOCK": str(tmp_path / "lock"),
            "SYNTH_DISK_HEALTH_PATH": str(repo_dir),
            "SYNTH_PAPER_ADVICE_LIFECYCLE_CHECKPOINT_STATE_PATH": str(
                tmp_path / "custom-checkpoint.json"
            ),
            "FAKE_PYTHON_CAPTURE_PATH": str(capture_path),
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    args = json.loads(capture_path.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert "--checkpoint-state-path" in args
    idx = args.index("--checkpoint-state-path")
    assert args[idx + 1] == str(tmp_path / "custom-checkpoint.json")


def test_wrapper_does_not_silently_ignore_invalid_log_threshold_overrides(tmp_path: Path) -> None:
    repo_dir = Path.cwd()
    env = os.environ.copy()
    env.update(
        {
            "VIRTUAL_ENV": str(tmp_path / "venv"),
            "SYNTH_REPO_DIR": str(repo_dir),
            "SYNTH_PAPER_ADVICE_LIFECYCLE_LOCK": str(tmp_path / "lock"),
            "SYNTH_DISK_HEALTH_PATH": str(repo_dir),
            "SYNTH_DISK_HEALTH_LOG_PATH": str(tmp_path / "missing.log"),
            "SYNTH_DISK_HEALTH_LOG_WARN_BYTES": "300",
            "SYNTH_DISK_HEALTH_LOG_CRITICAL_BYTES": "200",
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        cwd=repo_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert "FAILED runtime_disk_log_health_v1" in combined
    assert "Invalid log thresholds" in combined
    assert "[DISK_HEALTH][CRITICAL] aborting before candle ETL" in combined
