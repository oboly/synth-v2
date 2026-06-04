from __future__ import annotations

import ast
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.research.run_breath_phase_unknown_diagnostic_v1 import (
    SAFETY_MARKERS,
    RAW_PHASE_UNKNOWN,
    RAW_PHASE_NEUTRAL_TRANSITION,
    RAW_STATE_UNKNOWN,
    LIVE_SEMANTICS_CONSERVATIVE,
    SOURCE_ROW_MISSING,
    MAX_STALENESS,
    build_diagnostic_rows,
    build_recompute_by_sym_ts,
    build_recompute_lookup,
    classify_unknown_reason,
)


MODULE_PATH = Path("src/research/run_breath_phase_unknown_diagnostic_v1.py")

BASE_TS = datetime(2026, 5, 20, 12, 0, 0)


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _recomp_row(
    symbol: str,
    asof_ts: datetime,
    *,
    raw_phase: str = "NEUTRAL_TRANSITION",
    raw_state: str = "UNKNOWN",
    breath_phase: str = "UNKNOWN",
    breath_alignment: str = "UNKNOWN",
) -> dict:
    asof_str = asof_ts.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return {
        "symbol": symbol,
        "_asof_ts_dt": asof_ts,
        "asof_ts_utc": asof_str,
        "market_breath_phase_raw": raw_phase,
        "market_breath_state_raw": raw_state,
        "breath_phase": breath_phase,
        "breath_alignment": breath_alignment,
        "market_breath_confidence": "100.0",
        "compression_score": "10.0",
        "expansion_score": "20.0",
        "momentum_score": "-5.0",
        "reversal_pressure_score": "5.0",
        "relative_strength_score": "0.0",
        "btc_alignment_score": "0.0",
        "breadth_alignment_score": "15.0",
    }


def _event_row(
    symbol: str,
    event_ts: datetime,
    *,
    recompute_asof_ts_utc: str = "",
    breath_phase: str = "UNKNOWN",
    breath_alignment: str = "UNKNOWN",
) -> dict:
    return {
        "symbol": symbol,
        "_event_ts_dt": event_ts,
        "event_ts_utc": event_ts.replace(tzinfo=UTC).isoformat(),
        "breath_phase": breath_phase,
        "breath_alignment": breath_alignment,
        "recompute_asof_ts_utc": recompute_asof_ts_utc,
    }


def _recomp_asof_str(ts: datetime) -> str:
    return ts.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


class ClassifyUnknownReasonTests(unittest.TestCase):
    def test_no_recompute_row_gives_source_row_missing(self) -> None:
        ev = _event_row("XLM", BASE_TS)
        self.assertEqual(classify_unknown_reason(ev, None), SOURCE_ROW_MISSING)

    def test_raw_phase_unknown_gives_raw_phase_unknown(self) -> None:
        rrow = _recomp_row("XLM", BASE_TS - timedelta(hours=1), raw_phase="UNKNOWN")
        ev = _event_row("XLM", BASE_TS)
        self.assertEqual(classify_unknown_reason(ev, rrow), RAW_PHASE_UNKNOWN)

    def test_neutral_transition_gives_raw_phase_neutral_transition(self) -> None:
        rrow = _recomp_row("XLM", BASE_TS - timedelta(hours=1), raw_phase="NEUTRAL_TRANSITION")
        ev = _event_row("XLM", BASE_TS)
        self.assertEqual(classify_unknown_reason(ev, rrow), RAW_PHASE_NEUTRAL_TRANSITION)

    def test_raw_state_unknown_with_non_neutral_phase_gives_raw_state_unknown(self) -> None:
        rrow = _recomp_row(
            "XLM", BASE_TS - timedelta(hours=1),
            raw_phase="EXHALE_EXPANSION",
            raw_state="UNKNOWN",
        )
        ev = _event_row("XLM", BASE_TS)
        self.assertEqual(classify_unknown_reason(ev, rrow), RAW_STATE_UNKNOWN)

    def test_known_raw_phase_and_state_but_unknown_canonical_gives_live_semantics_conservative(self) -> None:
        rrow = _recomp_row(
            "XLM", BASE_TS - timedelta(hours=1),
            raw_phase="EXHALE_EXPANSION",
            raw_state="FORMING",
            breath_phase="UNKNOWN",
        )
        ev = _event_row("XLM", BASE_TS)
        self.assertEqual(classify_unknown_reason(ev, rrow), LIVE_SEMANTICS_CONSERVATIVE)


class BuildDiagnosticRowsTests(unittest.TestCase):
    def _build(
        self,
        events: list[dict],
        recomp_rows: list[dict],
    ) -> list[dict]:
        by_sym_ts = build_recompute_by_sym_ts(recomp_rows)
        lookup = build_recompute_lookup(recomp_rows)
        return build_diagnostic_rows(
            event_rows=events,
            recomp_by_sym_ts=by_sym_ts,
            recomp_lookup=lookup,
        )

    def test_produces_one_row_per_event(self) -> None:
        recomp_ts = BASE_TS - timedelta(hours=1)
        events = [
            _event_row("XLM", BASE_TS, recompute_asof_ts_utc=_recomp_asof_str(recomp_ts)),
            _event_row("XLM", BASE_TS + timedelta(hours=2),
                       recompute_asof_ts_utc=_recomp_asof_str(recomp_ts)),
        ]
        rrows = [_recomp_row("XLM", recomp_ts)]
        rows = self._build(events, rrows)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["research_only"] for r in rows))

    def test_neutral_transition_event_has_correct_unknown_reason(self) -> None:
        recomp_ts = BASE_TS - timedelta(hours=2)
        rrow = _recomp_row("XLM", recomp_ts, raw_phase="NEUTRAL_TRANSITION")
        ev = _event_row("XLM", BASE_TS, recompute_asof_ts_utc=_recomp_asof_str(recomp_ts))
        rows = self._build([ev], [rrow])
        self.assertEqual(rows[0]["unknown_reason"], RAW_PHASE_NEUTRAL_TRANSITION)
        self.assertTrue(rows[0]["breath_unknown"])

    def test_event_with_known_breath_has_no_unknown_reason(self) -> None:
        recomp_ts = BASE_TS - timedelta(hours=1)
        rrow = _recomp_row(
            "XLM", recomp_ts,
            raw_phase="EXHALE_EXPANSION", raw_state="CONFIRMED",
        )
        ev = _event_row(
            "XLM", BASE_TS,
            recompute_asof_ts_utc=_recomp_asof_str(recomp_ts),
            breath_phase="EXPANSION",
            breath_alignment="EARLY",
        )
        rows = self._build([ev], [rrow])
        self.assertFalse(rows[0]["breath_unknown"])
        self.assertIsNone(rows[0]["unknown_reason"])

    def test_missing_recompute_ts_falls_back_to_nearest_lookup(self) -> None:
        recomp_ts = BASE_TS - timedelta(hours=3)
        rrow = _recomp_row("XLM", recomp_ts, raw_phase="NEUTRAL_TRANSITION")
        # Event has no recompute_asof_ts_utc — should still find rrow via lookup
        ev = _event_row("XLM", BASE_TS, recompute_asof_ts_utc="")
        rows = self._build([ev], [rrow])
        self.assertEqual(rows[0]["raw_phase"], "NEUTRAL_TRANSITION")
        self.assertEqual(rows[0]["unknown_reason"], RAW_PHASE_NEUTRAL_TRANSITION)


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
