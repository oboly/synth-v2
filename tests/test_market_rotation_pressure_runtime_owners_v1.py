from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

WRITER_SERVICE = REPO_ROOT / "deploy/systemd/synth-market-rotation-pressure-writer.service"
WRITER_TIMER = REPO_ROOT / "deploy/systemd/synth-market-rotation-pressure-writer.timer"
PUBLISHER_SERVICE = REPO_ROOT / "docs/ops/systemd/synth-market-rotation-pressure-publisher.service"
PUBLISHER_TIMER = REPO_ROOT / "docs/ops/systemd/synth-market-rotation-pressure-publisher.timer"
OPS_DOC = REPO_ROOT / "docs/ops/market_rotation_pressure_runtime_owners_v1.md"

WRITER_WRAPPER = REPO_ROOT / "scripts/run_market_rotation_pressure_once.sh"
PUBLISHER_WRAPPER = REPO_ROOT / "scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh"

FORBIDDEN_LAYER_TOKENS = (
    "selection_engine",
    "decision_gate",
    "execution_planner",
)


def _without_broker_safety_marker_lines(text: str) -> str:
    """Strip lines that only *declare* the broker-write-permission safety
    marker (e.g. Environment=SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED),
    so remaining text can be checked for genuine broker invocation."""
    kept = []
    for line in text.splitlines():
        if re.match(r"environment=synth_broker_write_permission=not_granted$", line.strip()):
            continue
        kept.append(line)
    return "\n".join(kept)


def _parse_unit(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Minimal systemd unit-file parser preserving duplicate keys per section."""
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
    """Non-comment, non-blank unit-file lines, for content checks that must
    ignore explanatory comments (comments legitimately name forbidden
    surfaces to document that they are absent)."""
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
# Writer service
# ---------------------------------------------------------------------------

def test_writer_service_runs_as_gurk_with_canonical_working_directory():
    sections = _parse_unit(WRITER_SERVICE)
    assert _get(sections, "Service", "User") == "gurk"
    assert _get(sections, "Service", "WorkingDirectory") == "/home/gurk/projects/synth-v2"


def test_writer_service_is_gurkdb_bound_not_devlap():
    sections = _parse_unit(WRITER_SERVICE)
    assert _get(sections, "Unit", "ConditionHost") == "gurkdb"


def test_writer_service_invokes_only_existing_writer_wrapper_with_write_db():
    sections = _parse_unit(WRITER_SERVICE)
    exec_start = _get(sections, "Service", "ExecStart")
    assert exec_start is not None
    assert "scripts/run_market_rotation_pressure_once.sh" in exec_start
    assert "--write-db" in exec_start
    assert WRITER_WRAPPER.exists()


def test_writer_service_does_not_reference_forbidden_surfaces():
    text = _directive_lines(WRITER_SERVICE).lower()
    for token in ("reporting", "odroid", "profit_plan", "profit plan"):
        assert token not in text, f"writer service must not reference {token!r}"
    for token in FORBIDDEN_LAYER_TOKENS:
        assert token not in text, f"writer service must not reference {token!r}"
    assert "executor" not in text
    assert "broker" not in _without_broker_safety_marker_lines(text)


def test_writer_service_broker_write_permission_is_not_granted():
    sections = _parse_unit(WRITER_SERVICE)
    values = _get_all(sections, "Service", "Environment")
    broker_env = [v for v in values if v.startswith("SYNTH_BROKER_WRITE_PERMISSION=")]
    assert broker_env == ["SYNTH_BROKER_WRITE_PERMISSION=NOT_GRANTED"]


# ---------------------------------------------------------------------------
# Publisher service
# ---------------------------------------------------------------------------

def test_publisher_service_runs_as_theone_on_odroid():
    sections = _parse_unit(PUBLISHER_SERVICE)
    assert _get(sections, "Service", "User") == "theone"
    assert _get(sections, "Service", "WorkingDirectory") == "/home/theone/projects/synth-v2"


def test_publisher_service_invokes_only_read_only_wrapper_without_write_db():
    sections = _parse_unit(PUBLISHER_SERVICE)
    exec_start = _get(sections, "Service", "ExecStart")
    assert exec_start is not None
    assert "scripts/odroid/run_market_rotation_pressure_dashboard_render_once.sh" in exec_start
    assert "--write-db" not in exec_start
    assert PUBLISHER_WRAPPER.exists()


def test_publisher_service_does_not_invoke_history_or_pressure_runners():
    text = PUBLISHER_SERVICE.read_text()
    assert "run_market_rotation_history_v1" not in text
    assert "run_market_rotation_pressure_v1" not in text


def test_publisher_service_does_not_reference_forbidden_layers():
    text = _directive_lines(PUBLISHER_SERVICE).lower()
    for token in FORBIDDEN_LAYER_TOKENS:
        assert token not in text, f"publisher service must not reference {token!r}"
    assert "executor" not in text


# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------

_ONCALENDAR_MINUTES_RE = re.compile(r"OnCalendar=\*-\*-\* \*:(\d{2}(?:,\d{2})*):00 UTC")


def _timer_minutes(path: Path) -> tuple[int, ...]:
    sections = _parse_unit(path)
    value = _get(sections, "Timer", "OnCalendar")
    assert value is not None, f"{path} must define an explicit OnCalendar"
    match = _ONCALENDAR_MINUTES_RE.match(f"OnCalendar={value}")
    assert match is not None, f"{path} OnCalendar must be an explicit UTC wall-clock minute, got {value!r}"
    return tuple(int(minute) for minute in match.group(1).split(","))


def test_writer_timer_points_to_writer_service():
    sections = _parse_unit(WRITER_TIMER)
    assert _get(sections, "Timer", "Unit") == "synth-market-rotation-pressure-writer.service"


def test_publisher_timer_points_to_publisher_service():
    sections = _parse_unit(PUBLISHER_TIMER)
    assert _get(sections, "Timer", "Unit") == "synth-market-rotation-pressure-publisher.service"


def test_timers_use_explicit_utc_wall_clock_cadence_not_relative_interval():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        sections = _parse_unit(path)
        assert _get(sections, "Timer", "OnUnitActiveSec") is None, (
            f"{path} must not use a repeating OnUnitActiveSec timer for candle-aligned cadence"
        )
        _timer_minutes(path)  # raises if OnCalendar is missing/not wall-clock UTC


def test_writer_timer_uses_deterministic_native_15m_cadence():
    assert _timer_minutes(WRITER_TIMER) == (12, 27, 42, 57)
    assert _get(_parse_unit(WRITER_TIMER), "Timer", "RandomizedDelaySec") == "0"


def test_timers_are_persistent():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        sections = _parse_unit(path)
        assert _get(sections, "Timer", "Persistent") == "true"


def test_publisher_timer_has_bounded_randomized_delay():
    value = _get(_parse_unit(PUBLISHER_TIMER), "Timer", "RandomizedDelaySec")
    assert value is not None
    seconds = int(re.sub(r"[^0-9]", "", value))
    assert 0 < seconds <= 900, f"publisher RandomizedDelaySec={value} is not a bounded delay"


def test_writer_to_publisher_minimum_separation_is_preserved():
    writer_minutes = _timer_minutes(WRITER_TIMER)
    publisher_minutes = _timer_minutes(PUBLISHER_TIMER)
    assert publisher_minutes == (35,)
    publisher_minute = publisher_minutes[0]
    writer_minute = max(minute for minute in writer_minutes if minute < publisher_minute)

    writer_delay = int(re.sub(r"[^0-9]", "", _get(_parse_unit(WRITER_TIMER), "Timer", "RandomizedDelaySec")))
    publisher_delay = int(re.sub(r"[^0-9]", "", _get(_parse_unit(PUBLISHER_TIMER), "Timer", "RandomizedDelaySec")))

    writer_worst_case_start_sec = writer_minute * 60 + writer_delay
    publisher_best_case_start_sec = publisher_minute * 60

    effective_separation_sec = publisher_best_case_start_sec - writer_worst_case_start_sec
    assert effective_separation_sec >= 5 * 60, (
        "publisher must not be able to start before writer worst-case start "
        f"plus 5 minutes; got {effective_separation_sec}s"
    )
    assert publisher_minute not in writer_minutes


def test_timers_do_not_declare_cross_host_dependency():
    for path in (WRITER_TIMER, PUBLISHER_TIMER):
        text = _directive_lines(path)
        assert "ssh" not in text.lower()


# ---------------------------------------------------------------------------
# Repository architecture
# ---------------------------------------------------------------------------

def test_writer_wrapper_does_not_invoke_reporting():
    text = WRITER_WRAPPER.read_text()
    assert "src.reporting" not in text
    assert "run_market_rotation_pressure_dashboard_v1" not in text


def test_publisher_wrapper_does_not_invoke_market_data_writes():
    text = PUBLISHER_WRAPPER.read_text()
    assert "--write-db" not in text
    assert "run_market_rotation_history_v1" not in text
    assert "run_market_rotation_pressure_v1" not in text


def test_profit_plan_does_not_invoke_writer_or_publisher():
    profit_plan_files = list((REPO_ROOT / "src/reporting").glob("*profit_plan*.py"))
    profit_plan_files += list((REPO_ROOT / "src/research").glob("*profit_plan*.py"))
    assert profit_plan_files, "expected at least one Profit Plan source file to check"
    for path in profit_plan_files:
        text = path.read_text()
        assert "run_market_rotation_pressure_once" not in text
        assert "run_market_rotation_pressure_dashboard_render_once" not in text


def test_no_combined_cross_host_orchestrator_introduced():
    for path in (WRITER_SERVICE, WRITER_TIMER, PUBLISHER_SERVICE, PUBLISHER_TIMER):
        text = _directive_lines(path)
        assert "ssh" not in text.lower()

    publisher_sections = _parse_unit(PUBLISHER_SERVICE)
    publisher_exec_start = _get(publisher_sections, "Service", "ExecStart") or ""
    assert "synth-market-rotation-pressure-writer" not in publisher_exec_start

    writer_sections = _parse_unit(WRITER_SERVICE)
    writer_exec_start = _get(writer_sections, "Service", "ExecStart") or ""
    assert "synth-market-rotation-pressure-publisher" not in writer_exec_start


# ---------------------------------------------------------------------------
# Lock isolation (shared /tmp namespace between systemd and manual runs)
# ---------------------------------------------------------------------------

_DEFAULT_LOCK_RE = re.compile(r'LOCK_FILE="\$\{[A-Z_]+:-([^}]+)\}"')


def _default_lock_path(wrapper: Path) -> str:
    match = _DEFAULT_LOCK_RE.search(wrapper.read_text())
    assert match is not None, f"{wrapper} must define a default LOCK_FILE fallback"
    return match.group(1)


def test_writer_service_does_not_set_private_tmp_true():
    sections = _parse_unit(WRITER_SERVICE)
    assert _get(sections, "Service", "PrivateTmp") != "true"


def test_publisher_service_does_not_set_private_tmp_true():
    sections = _parse_unit(PUBLISHER_SERVICE)
    assert _get(sections, "Service", "PrivateTmp") != "true"


def test_wrappers_still_use_existing_default_tmp_lock_paths():
    assert _default_lock_path(WRITER_WRAPPER) == "/tmp/synth-market-rotation-pressure-v1.lock"
    assert _default_lock_path(PUBLISHER_WRAPPER) == "/tmp/synth-market-rotation-pressure-dashboard-v1.lock"


def test_services_do_not_override_wrapper_lock_env_vars():
    # No Environment= line overrides the lock-path env var, so each service
    # invocation resolves the wrapper's own /tmp default at runtime.
    writer_sections = _parse_unit(WRITER_SERVICE)
    writer_env = _get_all(writer_sections, "Service", "Environment")
    assert not any(v.startswith("SYNTH_ROTATION_PRESSURE_LOCK=") for v in writer_env)

    publisher_sections = _parse_unit(PUBLISHER_SERVICE)
    publisher_env = _get_all(publisher_sections, "Service", "Environment")
    assert not any(v.startswith("SYNTH_ROTATION_PRESSURE_DASHBOARD_LOCK=") for v in publisher_env)


def test_committed_services_share_host_tmp_namespace_with_manual_invocation():
    """A timer-triggered run and a manual `bash <wrapper>` invocation must
    contend for the same flock lock file. That requires: (a) the service
    does not set PrivateTmp=true (which would give the service its own
    private /tmp mount), and (b) the service does not override the
    wrapper's default lock-path env var to something private-tmp-only."""
    for service, wrapper, lock_env_prefix in (
        (WRITER_SERVICE, WRITER_WRAPPER, "SYNTH_ROTATION_PRESSURE_LOCK="),
        (PUBLISHER_SERVICE, PUBLISHER_WRAPPER, "SYNTH_ROTATION_PRESSURE_DASHBOARD_LOCK="),
    ):
        sections = _parse_unit(service)
        assert _get(sections, "Service", "PrivateTmp") != "true"
        env_values = _get_all(sections, "Service", "Environment")
        assert not any(v.startswith(lock_env_prefix) for v in env_values)
        assert _default_lock_path(wrapper).startswith("/tmp/")


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------

def test_ops_doc_names_both_owners_correctly():
    text = OPS_DOC.read_text()
    assert "gurk" in text
    assert "theone" in text
    assert "devlap" in text
    assert "Odroid" in text


def test_ops_doc_has_installation_and_rollback_sections():
    text = OPS_DOC.read_text()
    assert "## Installation Commands" in text
    assert "### Devlap installation" in text
    assert "### Odroid installation" in text
    assert "## Rollback" in text
    assert "### Devlap rollback" in text
    assert "### Odroid rollback" in text


def test_ops_doc_requires_multi_cycle_acceptance():
    text = OPS_DOC.read_text()
    assert "## Multi-Cycle Acceptance" in text
    assert "three" in text.lower()


def test_ops_doc_keeps_profit_plan_deferred_and_read_only():
    text = OPS_DOC.read_text()
    assert "Profit Plan" in text
    assert "deferred" in text.lower()


def test_ops_doc_states_no_host_systemd_mutation_occurred():
    text = OPS_DOC.read_text()
    assert "No host systemd unit has been" in text
