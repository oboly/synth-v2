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

def test_writer_service_runs_as_gurk_on_devlap():
    sections = _parse_unit(WRITER_SERVICE)
    assert _get(sections, "Service", "User") == "gurk"
    assert _get(sections, "Service", "WorkingDirectory") == "/home/gurk/projects/synth-v2"


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
        _timer_minute(path)  # raises if OnCalendar is missing/not wall-clock UTC


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
    publisher_delay = int(re.sub(r"[^0-9]", "", _get(_parse_unit(PUBLISHER_TIMER), "Timer", "RandomizedDelaySec")))

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
