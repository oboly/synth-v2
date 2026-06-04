from __future__ import annotations

import ast
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.research.run_context_event_coverage_gap_audit_v1 import (
    SAFETY_MARKERS,
    BREATH_CONTEXT,
    SYMBOL_REGIME_CONTEXT,
    MARKET_ONLY_CONTEXT,
    UNKNOWN_CONTEXT,
    USABLE_CONTEXT,
    CONTEXT_ROW_UNKNOWN,
    STALE_CONTEXT,
    PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE,
    MISSING_CONTEXT_ROW,
    MAX_STALENESS,
    build_audit_rows,
    build_lookup,
    classify_event,
    classify_from_event_level_fields,
)


MODULE_PATH = Path("src/research/run_context_event_coverage_gap_audit_v1.py")

BASE_TS = datetime(2026, 5, 1, 12, 0, 0)


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _ctx_row(
    symbol: str,
    asof_ts: datetime,
    *,
    breath_phase: str = "EXPANSION",
    breath_alignment: str = "ALIGNED",
    market_regime: str = "ALT_STRENGTH",
    btc_context: str = "BTC_OK",
    symbol_regime: str = "REL_STRENGTH",
    interval: str = "4h",
) -> dict:
    return {
        "symbol": symbol,
        "_asof_ts_dt": asof_ts,
        "asof_ts_utc": asof_ts.replace(tzinfo=UTC).isoformat(),
        "interval": interval,
        "breath_phase": breath_phase,
        "breath_alignment": breath_alignment,
        "market_regime": market_regime,
        "btc_context": btc_context,
        "symbol_regime": symbol_regime,
    }


def _unknown_ctx_row(symbol: str, asof_ts: datetime, interval: str = "4h") -> dict:
    return _ctx_row(
        symbol,
        asof_ts,
        breath_phase="UNKNOWN",
        breath_alignment="UNKNOWN",
        market_regime="UNKNOWN",
        btc_context="UNKNOWN",
        symbol_regime="UNKNOWN",
        interval=interval,
    )


def _event_row_bare(symbol: str, event_ts: datetime, interval: str = "4h") -> dict:
    """Event row with no embedded context fields (simulates pre-join state)."""
    return {
        "symbol": symbol,
        "_event_ts_dt": event_ts,
        "event_ts_utc": event_ts.replace(tzinfo=UTC).isoformat(),
        "interval": interval,
    }


def _event_row_with_context(
    symbol: str,
    event_ts: datetime,
    *,
    breath_phase: str = "UNKNOWN",
    breath_alignment: str = "UNKNOWN",
    market_regime: str = "UNKNOWN",
    btc_context: str = "UNKNOWN",
    symbol_regime: str = "UNKNOWN",
    fibo_context: str = "UNKNOWN",
    interval: str = "4h",
) -> dict:
    """Event row with embedded context fields (simulates event-level runner output)."""
    return {
        "symbol": symbol,
        "_event_ts_dt": event_ts,
        "event_ts_utc": event_ts.replace(tzinfo=UTC).isoformat(),
        "interval": interval,
        "breath_phase": breath_phase,
        "breath_alignment": breath_alignment,
        "market_regime": market_regime,
        "btc_context": btc_context,
        "symbol_regime": symbol_regime,
        "fibo_context": fibo_context,
    }


def _lookup(rows: list[dict]) -> dict:
    return build_lookup(rows)


# ── Context-range classification tests (secondary diagnostic) ─────────────────

class ContextRangeClassificationTests(unittest.TestCase):
    """These test classify_event — the staleness/range lookup path (secondary)."""

    def _classify(
        self,
        symbol: str,
        event_ts: datetime,
        ctx_rows: list[dict],
        recomp_rows: list[dict] | None = None,
        interval: str = "4h",
    ) -> dict:
        return classify_event(
            symbol=symbol,
            event_ts=event_ts,
            event_interval=interval,
            context_lookup=_lookup(ctx_rows),
            recompute_lookup=_lookup(recomp_rows or []),
        )

    def test_event_inside_range_with_known_context_is_usable(self) -> None:
        ctx = [_ctx_row("XLM", BASE_TS - timedelta(hours=1))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], USABLE_CONTEXT)
        self.assertIn("breath_phase", result["context_known_fields"])

    def test_event_inside_range_all_unknown_context_is_context_row_unknown(self) -> None:
        ctx = [_unknown_ctx_row("XLM", BASE_TS - timedelta(hours=2))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], CONTEXT_ROW_UNKNOWN)
        self.assertEqual(result["context_known_fields"], [])

    def test_event_after_context_range_end_plus_staleness_is_outside_range(self) -> None:
        ctx = [_ctx_row("XLM", BASE_TS - timedelta(days=10))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE)

    def test_event_before_context_range_start_is_outside_range(self) -> None:
        ctx = [_ctx_row("XLM", BASE_TS + timedelta(days=1))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE)

    def test_no_context_for_symbol_is_missing_context_row(self) -> None:
        ctx = [_ctx_row("BTC", BASE_TS - timedelta(hours=1))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], MISSING_CONTEXT_ROW)

    def test_stale_context_within_range_but_over_staleness(self) -> None:
        stale_ts = BASE_TS - timedelta(days=8)
        ctx = [
            _ctx_row("XLM", stale_ts),
            _ctx_row("XLM", BASE_TS + timedelta(hours=1)),
        ]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], STALE_CONTEXT)


# ── Event-level field classification tests (primary) ─────────────────────────

class EventLevelFieldClassificationTests(unittest.TestCase):
    """These test classify_from_event_level_fields — the primary coverage path."""

    def test_known_breath_phase_produces_breath_context(self) -> None:
        row = _event_row_with_context(
            "XLM", BASE_TS, breath_phase="EXPANSION", breath_alignment="ALIGNED"
        )
        result = classify_from_event_level_fields(row)
        self.assertEqual(result["issue_classification"], BREATH_CONTEXT)
        self.assertTrue(result["is_any_context"])
        self.assertTrue(result["is_material_context"])
        self.assertIn("breath_phase", result["event_level_known_fields"])

    def test_symbol_regime_without_breath_produces_symbol_regime_context(self) -> None:
        row = _event_row_with_context(
            "XLM", BASE_TS, symbol_regime="REL_STRENGTH",
            market_regime="ALT_STRENGTH", btc_context="BTC_OK",
        )
        result = classify_from_event_level_fields(row)
        self.assertEqual(result["issue_classification"], SYMBOL_REGIME_CONTEXT)
        self.assertTrue(result["is_material_context"])

    def test_market_only_context_is_not_material(self) -> None:
        row = _event_row_with_context(
            "XLM", BASE_TS, market_regime="RISK_ON", btc_context="BTC_OK",
        )
        result = classify_from_event_level_fields(row)
        self.assertEqual(result["issue_classification"], MARKET_ONLY_CONTEXT)
        self.assertTrue(result["is_any_context"])
        self.assertFalse(result["is_material_context"])

    def test_all_unknown_produces_unknown_context(self) -> None:
        row = _event_row_with_context("XLM", BASE_TS)
        result = classify_from_event_level_fields(row)
        self.assertEqual(result["issue_classification"], UNKNOWN_CONTEXT)
        self.assertFalse(result["is_any_context"])
        self.assertFalse(result["is_material_context"])

    def test_event_level_known_beats_stale_context_range(self) -> None:
        # Stale context-row lookup would give PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE,
        # but embedded fields are known → issue_classification must be event-level coverage.
        stale_ctx = [_ctx_row("XLM", BASE_TS - timedelta(days=10))]
        events = [
            _event_row_with_context(
                "XLM", BASE_TS,
                market_regime="RISK_ON", btc_context="BTC_OK",
                symbol_regime="REL_STRENGTH",
            )
        ]
        rows = build_audit_rows(
            event_rows=events,
            context_lookup=_lookup(stale_ctx),
            recompute_lookup={},
        )
        self.assertEqual(len(rows), 1)
        # Primary classification honours embedded fields
        self.assertEqual(rows[0]["issue_classification"], SYMBOL_REGIME_CONTEXT)
        # Range diagnostic still records the staleness problem
        self.assertEqual(rows[0]["context_range_issue"], PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE)

    def test_material_context_counts_breath_and_symbol_but_not_market_only(self) -> None:
        breath_row = _event_row_with_context("XLM", BASE_TS, breath_phase="EXPANSION")
        sym_row = _event_row_with_context("XLM", BASE_TS, symbol_regime="REL_STRENGTH")
        market_row = _event_row_with_context("XLM", BASE_TS, market_regime="RISK_ON")
        unknown_row = _event_row_with_context("XLM", BASE_TS)

        r_breath = classify_from_event_level_fields(breath_row)
        r_sym = classify_from_event_level_fields(sym_row)
        r_market = classify_from_event_level_fields(market_row)
        r_unknown = classify_from_event_level_fields(unknown_row)

        self.assertTrue(r_breath["is_material_context"])
        self.assertTrue(r_sym["is_material_context"])
        self.assertFalse(r_market["is_material_context"])
        self.assertFalse(r_unknown["is_material_context"])


# ── Build-rows integration ─────────────────────────────────────────────────────

class BuildAuditRowsTests(unittest.TestCase):
    def test_produces_one_row_per_event(self) -> None:
        events = [
            _event_row_bare("XLM", BASE_TS),
            _event_row_bare("XLM", BASE_TS + timedelta(hours=1)),
        ]
        ctx = [_ctx_row("XLM", BASE_TS - timedelta(hours=1))]
        rows = build_audit_rows(
            event_rows=events,
            context_lookup=_lookup(ctx),
            recompute_lookup={},
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["research_only"] for r in rows))

    def test_bare_event_row_without_embedded_fields_is_unknown_context(self) -> None:
        events = [_event_row_bare("XLM", BASE_TS)]
        ctx = [_ctx_row("XLM", BASE_TS - timedelta(hours=1))]
        rows = build_audit_rows(
            event_rows=events,
            context_lookup=_lookup(ctx),
            recompute_lookup={},
        )
        # No embedded context fields → UNKNOWN_CONTEXT from event-level
        self.assertEqual(rows[0]["issue_classification"], UNKNOWN_CONTEXT)
        # But context range finds it USABLE
        self.assertEqual(rows[0]["context_range_issue"], USABLE_CONTEXT)


# ── Safety & import checks ─────────────────────────────────────────────────────

class SafetyTests(unittest.TestCase):
    def test_safety_markers_all_zero(self) -> None:
        self.assertEqual(SAFETY_MARKERS["broker_calls"], 0)
        self.assertEqual(SAFETY_MARKERS["db_writes"], 0)
        self.assertEqual(SAFETY_MARKERS["order_submission"], 0)
        self.assertTrue(SAFETY_MARKERS["research_only"])

    def test_no_forbidden_imports(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        joined = "\n".join(imports)
        self.assertNotIn("decision_gate", joined)
        self.assertNotIn("execution_planner", joined)
        self.assertNotIn("executor", joined)
        self.assertNotIn("BitvavoClient", joined)
        self.assertNotIn("common.db", joined)


if __name__ == "__main__":
    unittest.main()
