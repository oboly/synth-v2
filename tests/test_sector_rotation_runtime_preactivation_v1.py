from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

WRITER_SERVICE = REPO_ROOT / "deploy/systemd/synth-sector-rotation-writer.service"
WRITER_TIMER = REPO_ROOT / "deploy/systemd/synth-sector-rotation-writer.timer"
PUBLISHER_SERVICE = REPO_ROOT / "docs/ops/systemd/synth-sector-rotation-publisher.service"
PUBLISHER_TIMER = REPO_ROOT / "docs/ops/systemd/synth-sector-rotation-publisher.timer"
OPS_DOC = REPO_ROOT / "docs/ops/sector_rotation_runtime_activation_v1.md"

WRITER_WRAPPER = REPO_ROOT / "scripts/run_sector_rotation_engine_once.sh"
PUBLISHER_WRAPPER = REPO_ROOT / "scripts/odroid/run_sector_rotation_dashboard_render_once.sh"

FORBIDDEN_LAYER_TOKENS = (
    "selection_engine",
    "decision_gate",
    "execution_planner",
)


def _without_broker_safety_marker_lines(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if re.match(r"environment=synth_broker_write_permission=not_granted$", line.strip()):
            continue
        kept.append(line)
    return "\n".join(kept)


def _parse_unit(path: Path) -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {}
    current = None
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        sections[current].append((key.strip(), value.strip()))
    return sections


def _directive_lines(path: Path) -> str:
    lines = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        lines.append(line)
    return "\n".join(lines)


def _get(sections: dict[str, list[tuple[str, str]]], section: str, key: str) -> str | None:
    for k, v in sections.get(section, []):
        if k == key:
            return v
    return None


def _get_all(sections: dict[str, list[tuple[str, str]]], section: str, key: str) -> list[str]:
    return [v for k, v in sections.get(section, []) if k == key]


# ---------------------------------------------------------------------------
# Wrapper syntax
# ---------------------------------------------------------------------------


def test_wrappers_pass_bash_syntax_check():
    for wrapper in (WRITER_WRAPPER, PUBLISHER_WRAPPER):
        result = subprocess.run(["bash", "-n", str(wrapper)], capture_output=True, text=True)
        assert result.returncode == 0, f"{wrapper}: {result.stderr}"


def test_writer_wrapper_rejects_unexpected_arguments():
    result = subprocess.run(["bash", str(WRITER_WRAPPER), "--bogus"], capture_output=True, text=True)
    assert result.returncode == 2
    result_no_args = subprocess.run(["bash", str(WRITER_WRAPPER)], capture_output=True, text=True)
    assert result_no_args.returncode == 2


def test_publisher_wrapper_accepts_zero_arguments_only():
    # A bare unexpected argument must be rejected with usage on stderr and
    # exit 2, without proceeding to venv activation, locking, or invoking
    # the Python runner (bounded: never reaches the DB).
    for bad_args in (["--bogus"], ["extra"], ["--venue", "bitvavo"]):
        result = subprocess.run(
            ["bash", str(PUBLISHER_WRAPPER), *bad_args], capture_output=True, text=True
        )
        assert result.returncode == 2, f"args={bad_args!r} stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "usage" in result.stderr.lower()
        assert "STARTED" not in result.stdout


# ---------------------------------------------------------------------------
# Writer service
# ---------------------------------------------------------------------------


def test_writer_service_runs_as_gurk_on_gurkdb():
    sections = _parse_unit(WRITER_SERVICE)
    assert _get(sections, "Service", "User") == "gurk"
    assert _get(sections, "Service", "WorkingDirectory") == "/home/gurk/projects/synth-v2"
    assert _get(sections, "Unit", "ConditionHost") == "gurkdb"


def test_writer_service_invokes_only_the_canonical_writer_wrapper_with_write_db():
    sections = _parse_unit(WRITER_SERVICE)
    exec_start = _get(sections, "Service", "ExecStart")
    assert exec_start is not None
    assert "scripts/run_sector_rotation_engine_once.sh" in exec_start
    assert "--write-db" in exec_start
    assert WRITER_WRAPPER.exists()


def test_writer_wrapper_invokes_only_the_canonical_writer_runner():
    text = WRITER_WRAPPER.read_text()
    assert "src.research.run_sector_rotation_engine_v1" in text
    assert "src.reporting" not in text
    assert "run_sector_rotation_dashboard_v1" not in text


def test_writer_service_does_not_reference_forbidden_surfaces():
    text = _directive_lines(WRITER_SERVICE).lower()
    for token in ("reporting", "odroid", "profit_plan", "profit plan"):
        assert token not in text, f"writer service must not reference {token!r}"
    for token in FORBIDDEN_LAYER_TOKENS:
        assert token not in text, f"writer service must not reference {token!r}"
    assert "executor" not in text
    assert "native_short" not in text
    assert "broker" not in _without_broker_safety_marker_lines(text)


def test_writer_service_broker_write_permission_is_not_granted():
    sections = _parse_unit(WRITER_SERVICE)
    values = _get_all(sections, "Service", "Environment")
    broker_env = [v for v in values if v.startswith("SYNTH_BROKER_WRITE_PERMISSION=")]
    assert broker_env == ["SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED"]
    live_env = [v for v in values if v.startswith("SYNTH_LIVE_EXECUTION_PERMISSION=")]
    assert live_env == ["SYNTH_LIVE_EXECUTION_PERMISSION=NOT_GRANTED"]


def test_writer_service_has_authorization_gate_pre_check():
    sections = _parse_unit(WRITER_SERVICE)
    exec_start_pre = _get(sections, "Service", "ExecStartPre")
    assert exec_start_pre is not None
    assert "verify_writer_capability_authorization_v1" in exec_start_pre
    assert "--capability sector_rotation_snapshot" in exec_start_pre


# ---------------------------------------------------------------------------
# Publisher service
# ---------------------------------------------------------------------------


def test_publisher_service_runs_as_theone_on_odroid():
    sections = _parse_unit(PUBLISHER_SERVICE)
    assert _get(sections, "Service", "User") == "theone"
    assert _get(sections, "Service", "WorkingDirectory") == "/home/theone/projects/synth-v2"


def test_publisher_service_invokes_only_the_canonical_reporting_runner():
    sections = _parse_unit(PUBLISHER_SERVICE)
    exec_start = _get(sections, "Service", "ExecStart")
    assert exec_start is not None
    assert "scripts/odroid/run_sector_rotation_dashboard_render_once.sh" in exec_start
    assert "--write-db" not in exec_start
    assert PUBLISHER_WRAPPER.exists()

    wrapper_text = PUBLISHER_WRAPPER.read_text()
    assert "src.reporting.run_sector_rotation_dashboard_v1" in wrapper_text
    assert "src.research" not in wrapper_text
    assert "run_sector_rotation_engine_v1" not in wrapper_text


def test_publisher_service_does_not_invoke_writer_runner():
    text = PUBLISHER_SERVICE.read_text()
    assert "run_sector_rotation_engine_v1" not in text
    assert "run_sector_rotation_engine_once" not in text


def test_publisher_service_does_not_reference_forbidden_layers():
    text = _directive_lines(PUBLISHER_SERVICE).lower()
    for token in FORBIDDEN_LAYER_TOKENS:
        assert token not in text, f"publisher service must not reference {token!r}"
    assert "executor" not in text
    assert "native_short" not in text


# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------

_ONCALENDAR_MINUTE_RE = re.compile(r"OnCalendar=\*-\*-\* \*:(\d{2}):00 UTC")


def _timer_minute(path: Path) -> int:
    sections = _parse_unit(path)
    value = _get(sections, "Timer", "OnCalendar")
    assert value is not None, f"{path} must define an explicit OnCalendar"
    match = _ONCALENDAR_MINUTE_RE.match(f"OnCalendar={value}")
    assert match is not None, f"{path} OnCalendar must be an explicit UTC wall-clock minute, got {value!r}"
    return int(match.group(1))


def test_writer_timer_points_to_writer_service():
    sections = _parse_unit(WRITER_TIMER)
    assert _get(sections, "Timer", "Unit") == "synth-sector-rotation-writer.service"


def test_publisher_timer_points_to_publisher_service():
    sections = _parse_unit(PUBLISHER_TIMER)
    assert _get(sections, "Timer", "Unit") == "synth-sector-rotation-publisher.service"


def test_timers_use_explicit_utc_wall_clock_cadence_not_relative_interval():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        sections = _parse_unit(path)
        assert _get(sections, "Timer", "OnUnitActiveSec") is None
        _timer_minute(path)


def test_timers_are_persistent():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        sections = _parse_unit(path)
        assert _get(sections, "Timer", "Persistent") == "true"


def test_timers_have_bounded_randomized_delay():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        sections = _parse_unit(path)
        value = _get(sections, "Timer", "RandomizedDelaySec")
        assert value is not None
        seconds = int(re.sub(r"[^0-9]", "", value))
        assert 0 < seconds <= 900, f"{path} RandomizedDelaySec={value} is not a bounded delay"


def test_writer_to_publisher_minimum_separation_is_preserved():
    writer_minute = _timer_minute(WRITER_TIMER)
    publisher_minute = _timer_minute(PUBLISHER_TIMER)

    writer_delay = int(re.sub(r"[^0-9]", "", _get(_parse_unit(WRITER_TIMER), "Timer", "RandomizedDelaySec")))

    writer_worst_case_start_sec = writer_minute * 60 + writer_delay
    publisher_best_case_start_sec = publisher_minute * 60

    effective_separation_sec = publisher_best_case_start_sec - writer_worst_case_start_sec
    assert effective_separation_sec >= 5 * 60, (
        "publisher must not be able to start before writer worst-case start "
        f"plus 5 minutes; got {effective_separation_sec}s"
    )
    assert publisher_minute != writer_minute


def test_timers_do_not_declare_cross_host_dependency():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        text = _directive_lines(path)
        assert "ssh" not in text.lower()


def test_timers_do_not_declare_requires_or_wants_on_their_own_service():
    # Requires=/Wants= on a timer's own service would pull the service in
    # as a dependency the moment the timer is started/enabled, conflating
    # scheduled activation with an acceptance run. Only the canonical
    # Timer/Unit= directive (which service OnCalendar= triggers) may name
    # the service.
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        sections = _parse_unit(path)
        assert _get(sections, "Unit", "Requires") is None, f"{path} must not declare [Unit] Requires="
        assert _get(sections, "Unit", "Wants") is None, f"{path} must not declare [Unit] Wants="


def test_writer_timer_still_declares_canonical_unit_directive():
    sections = _parse_unit(WRITER_TIMER)
    assert _get(sections, "Timer", "Unit") == "synth-sector-rotation-writer.service"


def test_publisher_timer_still_declares_canonical_unit_directive():
    sections = _parse_unit(PUBLISHER_TIMER)
    assert _get(sections, "Timer", "Unit") == "synth-sector-rotation-publisher.service"


# ---------------------------------------------------------------------------
# systemd-analyze verify
# ---------------------------------------------------------------------------


def test_units_pass_systemd_analyze_verify():
    unit_files = [WRITER_SERVICE, WRITER_TIMER, PUBLISHER_SERVICE, PUBLISHER_TIMER]
    result = subprocess.run(
        ["systemd-analyze", "verify", *[str(p) for p in unit_files]],
        capture_output=True,
        text=True,
    )
    # systemd-analyze verify may warn about paths that do not exist on this
    # sandbox host (e.g. /home/theone/... on a devlap checkout); only
    # capability-relevant errors referencing these exact unit files fail
    # the check, matching the ownership contract's scoped diagnostics rule.
    relevant_lines = [
        line
        for line in (result.stdout + result.stderr).splitlines()
        if any(str(p) in line or p.name in line for p in unit_files)
    ]
    hard_errors = [line for line in relevant_lines if "Failed to" in line and "No such file or directory" not in line]
    assert not hard_errors, "\n".join(relevant_lines)


# ---------------------------------------------------------------------------
# Repository architecture / no cross-invocation
# ---------------------------------------------------------------------------


def test_writer_wrapper_does_not_invoke_reporting():
    text = WRITER_WRAPPER.read_text()
    assert "src.reporting" not in text
    assert "run_sector_rotation_dashboard_v1" not in text


def test_publisher_wrapper_preserves_nonzero_exit_status_and_still_logs_finished(tmp_path):
    # Force the Python runner step to exit 1 (the real DATA_UNAVAILABLE exit
    # status) by putting a fake `python` ahead of PATH, and prove the
    # wrapper does not let `set -e` short-circuit it: FINISHED must still be
    # printed with the captured exit_status=1, and the wrapper itself must
    # exit 1 -- not 0, and not some other status from an unrelated later
    # failure once `set -e` unwinds past the intended capture point.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python"
    fake_python.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IEXEC)

    lock_file = tmp_path / "publisher.lock"
    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["VIRTUAL_ENV"] = str(tmp_path)  # any non-empty value skips venv activation
    env["SYNTH_SECTOR_ROTATION_DASHBOARD_LOCK"] = str(lock_file)
    env["SYNTH_REPO_DIR"] = str(REPO_ROOT)

    result = subprocess.run(
        ["bash", str(PUBLISHER_WRAPPER)], capture_output=True, text=True, env=env
    )

    assert result.returncode == 1, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "FINISHED runner=run_sector_rotation_dashboard_render_once exit_status=1" in result.stdout
    assert "SKIPPED" not in result.stdout


def test_publisher_wrapper_does_not_invoke_writer():
    text = PUBLISHER_WRAPPER.read_text()
    assert "--write-db" not in text
    assert "run_sector_rotation_engine_v1" not in text
    assert "run_sector_rotation_engine_once" not in text


def test_no_combined_cross_host_orchestrator_introduced():
    for path in (WRITER_SERVICE, WRITER_TIMER, PUBLISHER_SERVICE, PUBLISHER_TIMER):
        text = _directive_lines(path)
        assert "ssh" not in text.lower()

    publisher_sections = _parse_unit(PUBLISHER_SERVICE)
    publisher_exec_start = _get(publisher_sections, "Service", "ExecStart") or ""
    assert "synth-sector-rotation-writer" not in publisher_exec_start

    writer_sections = _parse_unit(WRITER_SERVICE)
    writer_exec_start = _get(writer_sections, "Service", "ExecStart") or ""
    assert "synth-sector-rotation-publisher" not in writer_exec_start


# ---------------------------------------------------------------------------
# Lock isolation
# ---------------------------------------------------------------------------

_DEFAULT_LOCK_RE = re.compile(r'LOCK_FILE="\$\{[A-Z_]+:-([^}]+)\}"')


def _default_lock_path(wrapper: Path) -> str:
    match = _DEFAULT_LOCK_RE.search(wrapper.read_text())
    assert match is not None, f"{wrapper} must define a default LOCK_FILE fallback"
    return match.group(1)


def test_writer_and_publisher_use_distinct_lock_paths():
    writer_lock = _default_lock_path(WRITER_WRAPPER)
    publisher_lock = _default_lock_path(PUBLISHER_WRAPPER)
    assert writer_lock != publisher_lock
    assert writer_lock == "/tmp/synth-sector-rotation-writer-v1.lock"
    assert publisher_lock == "/tmp/synth-sector-rotation-dashboard-v1.lock"


def test_writer_service_does_not_set_private_tmp_true():
    sections = _parse_unit(WRITER_SERVICE)
    assert _get(sections, "Service", "PrivateTmp") != "true"


def test_publisher_service_does_not_set_private_tmp_true():
    sections = _parse_unit(PUBLISHER_SERVICE)
    assert _get(sections, "Service", "PrivateTmp") != "true"


def test_services_do_not_override_wrapper_lock_env_vars():
    writer_sections = _parse_unit(WRITER_SERVICE)
    writer_env = _get_all(writer_sections, "Service", "Environment")
    assert not any(v.startswith("SYNTH_SECTOR_ROTATION_WRITER_LOCK=") for v in writer_env)

    publisher_sections = _parse_unit(PUBLISHER_SERVICE)
    publisher_env = _get_all(publisher_sections, "Service", "Environment")
    assert not any(v.startswith("SYNTH_SECTOR_ROTATION_DASHBOARD_LOCK=") for v in publisher_env)


# ---------------------------------------------------------------------------
# Writer authorization registry alignment (onboarded, still non-authorizing)
# ---------------------------------------------------------------------------


def test_writer_authorization_capability_is_registered_and_documented():
    from src.operations.validate_writer_capability_ownership_v1 import (
        CAPABILITY_IDENTITY,
        EXPECTED_CAPABILITY_IDS,
    )

    assert "sector_rotation_snapshot" in EXPECTED_CAPABILITY_IDS, (
        "registry onboarding for sector_rotation_snapshot is expected to have "
        "landed as its own reviewed change; update this test if that changed"
    )
    assert CAPABILITY_IDENTITY["sector_rotation_snapshot"] == "sector-rotation-snapshot-writer"
    ops_doc_text = OPS_DOC.read_text()
    assert "EXPECTED_CAPABILITY_IDS" in ops_doc_text
    assert "registry onboarding is complete" in ops_doc_text.lower()


def test_writer_capability_registry_entry_is_selected_pending_preflight_only():
    import json

    registry_path = REPO_ROOT / "deploy/ownership/writer_capability_ownership_v1.json"
    registry = json.loads(registry_path.read_text())
    cap = next(
        c for c in registry["capabilities"] if c.get("capability_id") == "sector_rotation_snapshot"
    )
    # gurkDB controlled acceptance landed (2026-08-11), but must remain
    # strictly non-authorizing: no production owner, no activation.
    assert cap["runtime_lifecycle"] == "ACCEPTED_PENDING_CUTOVER"
    assert cap["production_runtime_owner"] == "UNASSIGNED"
    assert cap["production_authorization_status"] == "UNASSIGNED"
    assert cap["acceptance_status"] == "ACCEPTED"
    assert cap["acceptance_evidence"]
    assert cap["production_decision_evidence"] == ""
    assert cap["observed_runtime_state"] == []


# ---------------------------------------------------------------------------
# Publisher purity (no write-capable research runner or broker import)
# ---------------------------------------------------------------------------


def test_publisher_module_has_no_write_capable_research_or_broker_import():
    import ast
    import inspect

    from src.reporting import run_sector_rotation_dashboard_v1 as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_substrings = ("executor", "decision_gate", "execution_planner", "broker", "research")
    for name in imported_modules:
        for forbidden in forbidden_substrings:
            assert forbidden not in name.lower(), f"unexpected import: {name}"


# ---------------------------------------------------------------------------
# Output path boundedness
# ---------------------------------------------------------------------------


def test_publisher_wrapper_output_paths_are_exactly_bounded():
    text = PUBLISHER_WRAPPER.read_text()
    assert "run_sector_rotation_dashboard_v1" in text
    # the wrapper delegates output-file naming entirely to the Python
    # runner's fixed sector-overview.html / sector-overview.json defaults;
    # it does not construct or pass any other output filename
    assert "sector-overview" not in text  # confirms no wrapper-side filename duplication/drift
    assert "--output-html" not in text
    assert "--output-json" not in text


def test_publisher_default_output_filenames_are_fixed():
    from src.reporting.run_sector_rotation_dashboard_v1 import DEFAULT_OUTPUT_ROOT

    assert str(DEFAULT_OUTPUT_ROOT) == "/var/www/html/synth"


# ---------------------------------------------------------------------------
# Rollback scope
# ---------------------------------------------------------------------------


def test_rollback_section_targets_only_this_lane():
    text = OPS_DOC.read_text()
    assert "## Rollback" in text
    rollback_section = text.split("## Rollback", 1)[1].split("## ", 1)[0]
    assert "sector_rotation_snapshot" in rollback_section or "this lane" in rollback_section
    assert "market_rotation_pressure" not in rollback_section
    assert "native_short" not in rollback_section
    assert "public_candle_freshness" not in rollback_section


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------


def test_ops_doc_states_no_host_mutation_and_not_yet_active():
    normalized = " ".join(OPS_DOC.read_text().lower().split())
    assert "not installed" in normalized
    assert "not enabled" in normalized
    assert "not production-accepted" in normalized or "not production accepted" in normalized


def test_ops_doc_has_installation_activation_rollback_and_observation_sections():
    text = OPS_DOC.read_text()
    for heading in (
        "## Installation Commands",
        "## Activation Order",
        "## Observation Requirements",
        "## Rollback",
        "## Stale and DATA_UNAVAILABLE Behavior",
        "## Cadence Evidence",
    ):
        assert heading in text, f"missing section: {heading}"


def test_ops_doc_names_both_candidate_hosts():
    text = OPS_DOC.read_text()
    assert "gurkdb" in text.lower()
    assert "odroid" in text.lower()


def test_ops_doc_forbids_cross_role_invocation():
    text = OPS_DOC.read_text()
    assert "must never invoke the writer" in text
    assert "must never invoke the publisher" in text


def test_ops_doc_correctly_warns_that_timer_start_can_trigger_a_real_cycle():
    normalized = " ".join(OPS_DOC.read_text().lower().split())

    # The corrected claims must be present: enable-alone does not start the
    # timer, but starting/enable --now does, and Persistent=true means that
    # start can immediately fire a missed run.
    assert "systemctl enable" in normalized and "alone" in normalized
    assert "does not start the timer" in normalized
    assert "persistent=true" in normalized
    assert "randomizeddelaysec" in normalized
    assert "potentially activating a real" in normalized

    # The earlier, incorrect claims must not reappear: removing
    # Requires=/Wants= does NOT make timer start execution-free, and
    # enabling/starting a timer is not merely "arming" a future cycle.
    assert "does not execute it immediately" not in normalized
    assert "only arms future" not in normalized
    assert "harmless" not in normalized or "not mean starting the timer is harmless" in normalized


def test_manual_acceptance_remains_conceptually_separate_from_timer_start():
    normalized = " ".join(OPS_DOC.read_text().replace("*", "").split())
    assert "conceptually separate from scheduled timer activation" in normalized
    assert "before either timer is started or enabled with" in normalized
