from __future__ import annotations

import ast
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.research.run_context_event_coverage_gap_audit_v1 import (
    SAFETY_MARKERS,
    USABLE_CONTEXT,
    CONTEXT_ROW_UNKNOWN,
    STALE_CONTEXT,
    PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE,
    MISSING_CONTEXT_ROW,
    MAX_STALENESS,
    build_audit_rows,
    build_lookup,
    classify_event,
)


MODULE_PATH = Path("src/research/run_context_event_coverage_gap_audit_v1.py")

BASE_TS = datetime(2026, 5, 1, 12, 0, 0)  # reference event timestamp


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


def _event_row(symbol: str, event_ts: datetime, interval: str = "4h") -> dict:
    return {
        "symbol": symbol,
        "_event_ts_dt": event_ts,
        "event_ts_utc": event_ts.replace(tzinfo=UTC).isoformat(),
        "interval": interval,
    }


def _lookup(rows: list[dict]) -> dict:
    return build_lookup(rows)


class ContextEventCoverageGapAuditV1Tests(unittest.TestCase):
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
        # Context ends at BASE_TS - 10 days; event is now (staleness is 7 days)
        ctx = [_ctx_row("XLM", BASE_TS - timedelta(days=10))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE)

    def test_event_before_context_range_start_is_outside_range(self) -> None:
        # All context rows are AFTER the event
        ctx = [_ctx_row("XLM", BASE_TS + timedelta(days=1))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], PROFILE_EVENT_OUTSIDE_CONTEXT_RANGE)

    def test_no_context_for_symbol_is_missing_context_row(self) -> None:
        ctx = [_ctx_row("BTC", BASE_TS - timedelta(hours=1))]
        result = self._classify("XLM", BASE_TS, ctx)
        self.assertEqual(result["issue_classification"], MISSING_CONTEXT_ROW)

    def test_stale_context_within_range_but_over_staleness(self) -> None:
        # Context row is 8 days old (staleness=7d), but within what would be the range
        # (range end is recent enough that event is inside range + staleness window)
        # Create two rows: one stale, one much later (so event is inside range)
        stale_ts = BASE_TS - timedelta(days=8)
        ctx = [
            _ctx_row("XLM", stale_ts),
            _ctx_row("XLM", BASE_TS + timedelta(hours=1)),  # after event → won't match
        ]
        result = self._classify("XLM", BASE_TS, ctx)
        # age > 7 days and event IS within range (range end = BASE_TS + 1h is after event)
        # so nearest is stale_ts, age = 8 days — classified as STALE_CONTEXT
        self.assertEqual(result["issue_classification"], STALE_CONTEXT)

    def test_build_audit_rows_produces_one_row_per_event(self) -> None:
        events = [
            _event_row("XLM", BASE_TS),
            _event_row("XLM", BASE_TS + timedelta(hours=1)),
        ]
        ctx = [_ctx_row("XLM", BASE_TS - timedelta(hours=1))]
        rows = build_audit_rows(
            event_rows=events,
            context_lookup=_lookup(ctx),
            recompute_lookup={},
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["research_only"] for r in rows))

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
