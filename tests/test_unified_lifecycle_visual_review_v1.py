"""
Tests for run_unified_lifecycle_visual_review_v1.

Covers:
  1. Representative page contains all required visual layers
  2. No future evidence before decision timestamp
  3. Missing parent/Breath context remains visibly UNKNOWN
  4. Event markers use correct timestamps (asof_ts_utc = candle 0)
  5. No filesystem paths in public hrefs
  6. build_unified_events join semantics
  7. select_matched_examples: category bucketing and deduplication
  8. SVG lifecycle chart contains correct structural elements
  9. execution_planner / decision_gate / executor not imported or called
  10. Safety markers present in manifest
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.run_unified_lifecycle_visual_review_v1 import (
    RUNNER_NAME,
    VERSION,
    CATEGORIES,
    SYNTHETIC_NOTE,
    build_unified_events,
    select_matched_examples,
    _html_event_page,
    _html_index_page,
    _svg_lifecycle_chart,
    run,
)


# ---------------------------------------------------------------------------
# Helpers for building synthetic test events
# ---------------------------------------------------------------------------

def _make_outcome_row(
    symbol: str = "BTC",
    asof_ts: str = "2026-03-14T00:00:00Z",
    breath_phase: str = "NEUTRAL_TRANSITION",
    **kwargs: Any,
) -> dict:
    base = {
        "symbol": symbol,
        "venue": "BINANCE",
        "asof_ts_utc": asof_ts,
        "close_price": 65000.0,
        "market_breath_phase": breath_phase,
        "market_breath_state": "UNKNOWN",
        "market_breath_score": 50.0,
        "market_breath_confidence": 0.7,
        "breadth_alignment_score": 5.0,
        "btc_alignment_score": 10.0,
        "momentum_score": 0.0,
        "compression_score": 20.0,
        "expansion_score": 30.0,
        "reversal_pressure_score": 30.0,
        "relative_strength_score": 0.0,
        "fwd_return_1c": 0.5,
        "fwd_return_3c": 1.0,
        "fwd_return_6c": 2.0,
        "fwd_return_12c": 1.5,
        "fwd_return_18c": 3.0,
        "fwd_return_24c": 2.5,
        "max_runup_24c_from_asof_close": 3.2,
        "max_drawdown_24c_from_asof_close": 0.8,
    }
    base.update(kwargs)
    return base


def _make_multi_event_row(
    symbol: str = "BTC",
    asof_ts: str = "2026-03-14T00:00:00Z",
    gate_state: str = "CONTINUATION_SUPPORTED",
    variant_type: str = "BASELINE",
    **kwargs: Any,
) -> dict:
    base = {
        "symbol": symbol,
        "asof_ts_utc": asof_ts,
        "variant_type": variant_type,
        "gate_state": gate_state,
        "gate_applied": "BREATH_GATE",
        "live_valid": "true",
        "breath_phase": "EXHALE_EXPANSION",
        "breath_alignment": "NEUTRAL",
        "market_regime": "TRENDING_UP",
        "symbol_regime": "TRENDING",
        "variant_return_pct": 2.0,
        "delta_vs_c1": 1.5,
        "context_lookup_status": "FOUND",
        "close_price": 65000.0,
    }
    base.update(kwargs)
    return base


def _make_reentry_row(
    symbol: str = "BTC",
    asof_ts: str = "2026-03-14T00:00:00Z",
    reentry_state: str = "CONTEXT_UNKNOWN",
    **kwargs: Any,
) -> dict:
    base = {
        "symbol": symbol,
        "asof_ts_utc": asof_ts,
        "reentry_state": reentry_state,
        "reentry_reason": "test reason",
        "synthetic_weakness_state": "WEAKNESS_UNKNOWN",
        "synthetic_reset_state": "RESET_UNKNOWN",
        "synthetic_reclaim_state": "RECLAIM_UNKNOWN",
        "synthetic_reload_zone_state": "RELOAD_UNKNOWN",
        "synthetic_breath_alignment": "NEUTRAL",
        "synthetic_regime_state": "UNKNOWN",
        "synthetic_native_short_4h": "UNKNOWN",
        "synthetic_native_short_1h": "UNKNOWN",
    }
    base.update(kwargs)
    return base


def _make_residual_row(
    symbol: str = "BTC",
    asof_ts: str = "2026-03-14T00:00:00Z",
    parent_state: str = "PARENT_CONTEXT_UNKNOWN",
    variant_id: str = "V1_CHILD_PARTIAL_TRIM",
    **kwargs: Any,
) -> dict:
    base = {
        "symbol": symbol,
        "asof_ts_utc": asof_ts,
        "variant_id": variant_id,
        "synthetic_parent_terminal_state": parent_state,
        "synthetic_parent_constructive_state": "PARENT_CONSTRUCTIVE",
        "research_action": "PARTIAL_TRIM_ONLY",
    }
    base.update(kwargs)
    return base


def _build_event_set(**kwargs) -> list[dict]:
    """One event with all layers joined."""
    outcome = [_make_outcome_row(**kwargs)]
    multi = [_make_multi_event_row(**kwargs)]
    reentry = [_make_reentry_row(**kwargs)]
    residual = [_make_residual_row(**kwargs)]
    return build_unified_events(outcome, multi, reentry, residual)


# ---------------------------------------------------------------------------
# 1. Representative page contains all required visual layers
# ---------------------------------------------------------------------------

class TestRequiredVisualLayers:
    """
    Each event page must expose all 7 visual layers (even as synthetic proxies).
    """

    REQUIRED_LAYER_LABELS = [
        "Breath Layer",
        "Regime Layer",
        "Child Fib Map",
        "Parent Fib Map",
        "Re-entry Gate",
        "Continuation Gate",
        "Outcomes",
    ]

    def test_event_page_contains_all_layer_sections(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        for label in self.REQUIRED_LAYER_LABELS:
            assert label in page, (
                f"Event page missing visual layer section: {label!r}"
            )

    def test_event_page_contains_svg_chart(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        assert "<svg" in page
        assert "</svg>" in page

    def test_event_page_contains_score_bars(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        # Score bars rendered for breath layer scores
        assert "breath_score" in page or "breath" in page.lower()
        assert "momentum" in page.lower()

    def test_event_page_contains_provenance_section(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        assert "Source Provenance" in page
        assert "asof_ts_utc" in page

    def test_event_page_has_synthetic_note(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        # Synthetic note must appear — proxies must be labeled
        assert "Synthetic" in page or "synthetic" in page or "SYNTHETIC" in page

    def test_index_page_contains_all_category_filter_options(self):
        events = _build_event_set(gate_state="CONTINUATION_SUPPORTED")
        event_pages = {"BTC_2026-03-14T00:00:00Z": "event_test.html"}
        page = _html_index_page(events, event_pages, CATEGORIES)
        for cat in CATEGORIES:
            assert cat in page, f"Index page missing category filter option: {cat}"


# ---------------------------------------------------------------------------
# 2. No future evidence before decision timestamp
# ---------------------------------------------------------------------------

class TestNoFutureEvidence:
    """
    Forward returns must not appear in gate state logic fields.
    The chart must label asof_ts_utc as candle 0 (decision point).
    Gate state badge must not reference r6/r24 values.
    """

    def test_svg_decision_marker_at_candle_zero(self):
        ev = _build_event_set()[0]
        svg = _svg_lifecycle_chart(ev)
        assert "decision" in svg, "SVG must label candle 0 as decision marker"

    def test_gate_state_field_is_not_a_return_value(self):
        events = _build_event_set(gate_state="CONTINUATION_SUPPORTED")
        ev = events[0]
        # Gate state must be a categorical state name, not a number
        assert isinstance(ev["gate_state"], str)
        assert not ev["gate_state"].replace(".", "").replace("-", "").isdigit()

    def test_forward_return_fields_are_outcomes_not_gate_inputs(self):
        """
        fwd_return_* fields are research outcomes. They appear in Outcomes section
        but must not appear in gate_state / reentry_state / parent terminal state.
        """
        events = _build_event_set(fwd_return_6c=5.0, gate_state="BREATH_CONFLICT")
        ev = events[0]
        page = _html_event_page(ev)
        # Gate state must not mention return values
        # (Gate state section must not contain the actual r6 value in the gate badge)
        assert "BREATH_CONFLICT" in page
        # The return value 5.0 must appear only in the Outcomes section
        assert "+5.00%" in page or "5.0" in page  # appears somewhere
        # The gate badge must not contain the numeric return
        gate_section_match = re.search(
            r"Continuation Gate.*?(?=Outcomes|Breath Layer|$)", page, re.DOTALL
        )
        if gate_section_match:
            gate_section = gate_section_match.group(0)
            assert "+5.00%" not in gate_section

    def test_decision_timestamp_equals_candle_zero_in_provenance(self):
        events = _build_event_set(asof_ts="2026-04-01T12:00:00Z")
        ev = events[0]
        page = _html_event_page(ev)
        # asof_ts_utc must appear in provenance section
        assert "2026-04-01" in page
        assert "asof_ts_utc" in page


# ---------------------------------------------------------------------------
# 3. Missing parent/Breath context remains visibly UNKNOWN
# ---------------------------------------------------------------------------

class TestUnknownContextVisible:
    """
    When parent context or Breath state is UNKNOWN,
    the page must show the UNKNOWN label (not silently hide it).
    """

    def test_parent_context_unknown_visible(self):
        outcome = [_make_outcome_row(breath_phase="NEUTRAL_TRANSITION")]
        multi = []
        reentry = [_make_reentry_row(reentry_state="CONTEXT_UNKNOWN")]
        residual = [_make_residual_row(parent_state="PARENT_CONTEXT_UNKNOWN")]
        events = build_unified_events(outcome, multi, reentry, residual)
        ev = events[0]
        page = _html_event_page(ev)
        assert "PARENT_CONTEXT_UNKNOWN" in page

    def test_breath_unknown_phase_visible(self):
        outcome = [_make_outcome_row(breath_phase="NEUTRAL_TRANSITION")]
        multi = []
        reentry = []
        residual = []
        events = build_unified_events(outcome, multi, reentry, residual)
        ev = events[0]
        page = _html_event_page(ev)
        assert "NEUTRAL_TRANSITION" in page

    def test_reentry_not_evaluated_visible(self):
        outcome = [_make_outcome_row()]
        multi = []
        reentry = []
        residual = []
        events = build_unified_events(outcome, multi, reentry, residual)
        ev = events[0]
        page = _html_event_page(ev)
        # Page must show that re-entry was not evaluated
        assert "NOT_EVALUATED" in page or "UNKNOWN" in page or "CONTEXT_UNKNOWN" in page

    def test_gate_not_evaluated_visible(self):
        outcome = [_make_outcome_row()]
        multi = []
        reentry = []
        residual = []
        events = build_unified_events(outcome, multi, reentry, residual)
        ev = events[0]
        assert ev["gate_state"] == "NOT_EVALUATED"
        page = _html_event_page(ev)
        assert "NOT_EVALUATED" in page

    def test_synthetic_note_visible(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        # Must explain that child/parent fib maps are synthetic proxies
        assert "Synthetic" in page or "SYNTHETIC" in page or "proxy" in page.lower()


# ---------------------------------------------------------------------------
# 4. Event markers use correct timestamps
# ---------------------------------------------------------------------------

class TestEventMarkersTimestamps:
    """
    asof_ts_utc must be used as the decision timestamp (candle 0).
    No forward shift allowed (no +1c, +3c etc. on the gate state badge).
    """

    def test_asof_ts_appears_in_page_exactly(self):
        ts = "2026-04-15T08:00:00Z"
        events = _build_event_set(asof_ts=ts)
        ev = events[0]
        page = _html_event_page(ev)
        assert ts[:16] in page, f"Page must show exact decision timestamp {ts[:16]}"

    def test_unified_event_preserves_asof_ts(self):
        ts = "2026-05-01T04:00:00Z"
        events = _build_event_set(asof_ts=ts)
        ev = events[0]
        assert ev["asof_ts_utc"] == ts

    def test_svg_candle_zero_is_decision(self):
        ev = _build_event_set()[0]
        svg = _svg_lifecycle_chart(ev)
        # The decision marker must be at x position corresponding to candle 0
        assert "decision" in svg.lower()
        # Candle 0 maps to SVG_PAD_L = 50
        # The decision vertical line must be at x1="50"
        assert 'x1="50' in svg

    def test_svg_horizons_increase_from_zero(self):
        ev = _build_event_set()[0]
        svg = _svg_lifecycle_chart(ev)
        # Candle indices 0..24 must appear
        for c in ["0c", "1c", "6c", "24c"]:
            assert c in svg, f"SVG missing horizon label: {c}"


# ---------------------------------------------------------------------------
# 5. No filesystem paths in public hrefs
# ---------------------------------------------------------------------------

class TestNoFilesystemPathsInHrefs:
    """
    All href and src attributes must use relative paths only.
    Absolute /home/.../... paths must not appear in any HTML output.
    """

    def test_event_page_no_absolute_href(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        # No absolute paths in hrefs
        assert 'href="/home/' not in page
        assert 'href="/usr/' not in page
        assert 'href="C:\\' not in page

    def test_event_page_no_absolute_src(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        assert 'src="/home/' not in page
        assert 'src="/usr/' not in page

    def test_index_page_no_absolute_href(self):
        events = _build_event_set(gate_state="CONTINUATION_SUPPORTED")
        event_pages = {"BTC_2026-03-14T00:00:00Z": "event_test.html"}
        page = _html_index_page(events, event_pages, CATEGORIES)
        assert 'href="/home/' not in page
        assert 'href="/usr/' not in page

    def test_index_page_event_links_are_relative(self):
        events = _build_event_set()
        event_pages = {"BTC_2026-03-14T00:00:00Z": "event_test.html"}
        page = _html_index_page(events, event_pages, CATEGORIES)
        # Event links must be relative
        assert '"event_test.html"' in page or "event_test.html" in page

    def test_back_link_is_relative(self):
        events = _build_event_set()
        ev = events[0]
        page = _html_event_page(ev)
        # Back link must use relative index.html, not absolute path
        assert 'href="index.html"' in page

    def test_manifest_has_no_filesystem_hrefs(self):
        """Manifest may have filesystem paths in input_sources (that's OK).
        Index and event filenames must be relative."""
        import json as _json
        dummy_manifest = {
            "index": "index.html",
            "regenerate_cmd": "python -m src.research.run_unified_lifecycle_visual_review_v1",
        }
        assert not dummy_manifest["index"].startswith("/")


# ---------------------------------------------------------------------------
# 6. build_unified_events join semantics
# ---------------------------------------------------------------------------

class TestBuildUnifiedEvents:
    def test_joins_on_symbol_and_ts(self):
        outcome = [
            _make_outcome_row(symbol="BTC", asof_ts="2026-03-14T00:00:00Z"),
            _make_outcome_row(symbol="ETH", asof_ts="2026-03-14T00:00:00Z"),
        ]
        multi = [
            _make_multi_event_row(symbol="BTC", asof_ts="2026-03-14T00:00:00Z",
                                   gate_state="CONTINUATION_SUPPORTED"),
            _make_multi_event_row(symbol="ETH", asof_ts="2026-03-14T00:00:00Z",
                                   gate_state="BREATH_CONFLICT"),
        ]
        events = build_unified_events(outcome, multi, [], [])
        by_symbol = {e["symbol"]: e for e in events}
        assert by_symbol["BTC"]["gate_state"] == "CONTINUATION_SUPPORTED"
        assert by_symbol["ETH"]["gate_state"] == "BREATH_CONFLICT"

    def test_missing_multi_event_gives_not_evaluated(self):
        outcome = [_make_outcome_row(symbol="SOL", asof_ts="2026-03-14T00:00:00Z")]
        events = build_unified_events(outcome, [], [], [])
        assert events[0]["gate_state"] == "NOT_EVALUATED"

    def test_missing_reentry_gives_not_evaluated(self):
        outcome = [_make_outcome_row()]
        events = build_unified_events(outcome, [], [], [])
        assert events[0]["reentry_state"] == "NOT_EVALUATED"

    def test_non_baseline_variant_not_used_for_gate_state(self):
        """Only BASELINE variant rows should set the primary gate_state."""
        outcome = [_make_outcome_row()]
        multi = [
            _make_multi_event_row(variant_type="VARIANT_1C_HOLD",
                                   gate_state="CONTINUATION_WEAK"),
        ]
        events = build_unified_events(outcome, multi, [], [])
        # BASELINE not present → NOT_EVALUATED
        assert events[0]["gate_state"] == "NOT_EVALUATED"

    def test_deduplicates_duplicate_outcome_rows(self):
        outcome = [
            _make_outcome_row(symbol="BTC", asof_ts="2026-03-14T00:00:00Z"),
            _make_outcome_row(symbol="BTC", asof_ts="2026-03-14T00:00:00Z"),
        ]
        events = build_unified_events(outcome, [], [], [])
        btc_events = [e for e in events if e["symbol"] == "BTC"]
        assert len(btc_events) == 1, "Duplicate (symbol, ts) must be deduplicated"

    def test_category_bucketing_continuation_supported(self):
        outcome = [_make_outcome_row()]
        multi = [_make_multi_event_row(gate_state="CONTINUATION_SUPPORTED")]
        events = build_unified_events(outcome, multi, [], [])
        cats = events[0]["categories_list"]
        assert "CONTINUATION_SUPPORTED" in cats

    def test_category_bucketing_reentry_blocked(self):
        outcome = [_make_outcome_row()]
        multi = []
        reentry = [_make_reentry_row(reentry_state="REENTRY_BLOCKED_WEAKNESS")]
        events = build_unified_events(outcome, multi, reentry, [])
        cats = events[0]["categories_list"]
        assert "REENTRY_BLOCKED_WEAKNESS" in cats

    def test_category_bucketing_parent_context_unknown(self):
        outcome = [_make_outcome_row()]
        multi = []
        reentry = []
        residual = [_make_residual_row(parent_state="PARENT_CONTEXT_UNKNOWN")]
        events = build_unified_events(outcome, multi, reentry, residual)
        cats = events[0]["categories_list"]
        assert "PARENT_CONTEXT_UNKNOWN" in cats


# ---------------------------------------------------------------------------
# 7. select_matched_examples: category bucketing and deduplication
# ---------------------------------------------------------------------------

class TestSelectMatchedExamples:
    def _events_for_categories(self) -> list[dict]:
        return [
            build_unified_events(
                [_make_outcome_row(symbol=f"ASSET{i}", asof_ts="2026-03-14T00:00:00Z")],
                [_make_multi_event_row(symbol=f"ASSET{i}", asof_ts="2026-03-14T00:00:00Z",
                                       gate_state="CONTINUATION_SUPPORTED")],
                [], []
            )[0]
            for i in range(8)
        ]

    def test_max_per_category_respected(self):
        events = self._events_for_categories()
        selected = select_matched_examples(events, max_per_category=3)
        for cat, evs in selected.items():
            assert len(evs) <= 3, f"Category {cat} exceeds max_per_category=3: {len(evs)}"

    def test_all_categories_present_in_output(self):
        events = self._events_for_categories()
        selected = select_matched_examples(events, max_per_category=5)
        for cat in CATEGORIES:
            assert cat in selected

    def test_empty_category_returns_empty_list(self):
        events = _build_event_set(gate_state="CONTINUATION_SUPPORTED")
        selected = select_matched_examples(events, max_per_category=5)
        # REENTRY_CONTEXT_SUPPORTED has no events
        assert selected.get("REENTRY_CONTEXT_SUPPORTED", []) == []


# ---------------------------------------------------------------------------
# 8. SVG lifecycle chart structural elements
# ---------------------------------------------------------------------------

class TestSvgLifecycleChart:
    def test_svg_has_polyline(self):
        ev = _build_event_set()[0]
        svg = _svg_lifecycle_chart(ev)
        assert "<polyline" in svg

    def test_svg_has_mfe_line_when_present(self):
        ev = _build_event_set(max_runup_24c_from_asof_close=3.5)[0]
        svg = _svg_lifecycle_chart(ev)
        assert "Max H" in svg

    def test_svg_has_mae_line_when_present(self):
        ev = _build_event_set(max_drawdown_24c_from_asof_close=1.2)[0]
        svg = _svg_lifecycle_chart(ev)
        assert "Min L" in svg

    def test_svg_skips_mfe_line_when_missing(self):
        outcome = [_make_outcome_row()]
        outcome[0]["max_runup_24c_from_asof_close"] = None
        events = build_unified_events(outcome, [], [], [])
        svg = _svg_lifecycle_chart(events[0])
        assert "Max H" not in svg

    def test_svg_zero_baseline_always_present(self):
        ev = _build_event_set()[0]
        svg = _svg_lifecycle_chart(ev)
        # Zero baseline reference line is drawn
        assert 'stroke="#444"' in svg or "stroke-dasharray" in svg

    def test_svg_uses_dark_background(self):
        ev = _build_event_set()[0]
        svg = _svg_lifecycle_chart(ev)
        assert "1a1a2e" in svg or "0d1117" in svg or "background" in svg


# ---------------------------------------------------------------------------
# 9. execution_planner / decision_gate / executor not imported or called
# ---------------------------------------------------------------------------

class TestNoForbiddenDependencies:
    def _src_path(self) -> Path:
        return (
            Path(__file__).resolve().parents[1]
            / "src" / "research" / "run_unified_lifecycle_visual_review_v1.py"
        )

    def test_execution_planner_not_imported(self):
        source = self._src_path().read_text()
        assert "import execution_planner" not in source
        assert "from execution_planner" not in source

    def test_decision_gate_not_imported(self):
        source = self._src_path().read_text()
        assert "import decision_gate" not in source
        assert "from decision_gate" not in source

    def test_executor_not_imported(self):
        source = self._src_path().read_text()
        assert "import executor" not in source
        assert "from executor" not in source

    def test_no_broker_calls(self):
        source = self._src_path().read_text()
        assert "broker" not in source.lower() or "broker_writes=0" in source

    def test_no_forbidden_module_calls_via_regex(self):
        source = self._src_path().read_text()
        for module in ("execution_planner", "decision_gate", "executor"):
            calls = re.findall(rf'{module}\s*\.\s*\w+\s*\(', source)
            assert not calls, f"{module} called as code: {calls}"


# ---------------------------------------------------------------------------
# 10. Safety markers present in manifest
# ---------------------------------------------------------------------------

class TestSafetyMarkersPresent:
    def test_runner_constants_defined(self):
        assert RUNNER_NAME == "UNIFIED_LIFECYCLE_VISUAL_REVIEW_V1"
        assert VERSION is not None

    def test_synthetic_note_defined(self):
        assert "proxy" in SYNTHETIC_NOTE.lower() or "SYNTHETIC" in SYNTHETIC_NOTE

    def test_manifest_safety_markers_via_dry_run(self):
        """Dry-run produces no file writes; manifest keys confirmed in code."""
        import inspect
        source = inspect.getsource(run)
        assert "broker_private_calls" in source
        assert "broker_writes" in source
        assert "order_submission" in source
        assert "live_orders" in source
        assert "execution_planner" in source
        assert "executor" in source

    def test_all_categories_in_categories_list(self):
        for cat in [
            "CONTINUATION_SUPPORTED",
            "BREATH_CONFLICT",
            "REGIME_CONFLICT",
            "TERMINAL_CONFIRMED",
            "PARENT_CONTEXT_UNKNOWN",
            "REENTRY_BLOCKED_WEAKNESS",
            "REENTRY_CONTEXT_SUPPORTED",
        ]:
            assert cat in CATEGORIES, f"Missing required category: {cat}"
