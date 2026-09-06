from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from src.research.run_historical_market_breath_source_recompute_v1 import (
    REPORT_NAME,
    SAFETY_MARKERS,
    build_manifest,
    breadth_dummy_rows_at_asof,
    build_recomputed_row,
    resolve_assets,
    parse_ts,
    print_summary,
)


MODULE_PATH = Path("src/research/run_historical_market_breath_source_recompute_v1.py")


class HistoricalMarketBreathSourceRecomputeV1Tests(unittest.TestCase):
    def test_recompute_row_maps_known_raw_phase(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "WLD",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "CONFIRMED",
                "relative_strength_score": 30.0,
                "momentum_score": 25.0,
                "btc_alignment_score": 12.0,
                "breadth_alignment_score": 5.0,
                "market_breath_confidence": 100.0,
            }
        )
        self.assertEqual(row["breath_phase"], "EXPANSION")

    def test_unknown_raw_phase_remains_unknown(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "NEAR",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
            }
        )
        self.assertEqual(row["breath_phase"], "UNKNOWN")

    def test_unknown_alignment_remains_unknown(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "HYPE",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "SIDEWAYS",
                "relative_strength_score": 5.0,
                "momentum_score": 15.0,
            }
        )
        self.assertEqual(row["breath_alignment"], "UNKNOWN")

    def test_symbol_regime_uses_existing_helper_thresholds(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "TAO",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "NEUTRAL_TRANSITION",
                "market_breath_state": "UNKNOWN",
                "relative_strength_score": 25.0,
                "momentum_score": 50.0,
            }
        )
        self.assertEqual(row["symbol_regime"], "REL_STRENGTH")

    def test_missing_source_input_fails_cleanly(self) -> None:
        with self.assertRaises(ValueError):
            build_recomputed_row({"symbol": "WLD"})

    def test_output_includes_source_refs_and_research_only(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "ALGO",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "COLLAPSE_RESET",
                "market_breath_state": "RESET",
                "relative_strength_score": -25.0,
                "momentum_score": -50.0,
            }
        )
        self.assertTrue(row["research_only"])
        self.assertTrue(row["source_refs"])
        self.assertEqual(row["source_refs"][0]["source"], REPORT_NAME)

    def test_manifest_safety_markers_exist(self) -> None:
        manifest = build_manifest(
            args=type(
                "Args",
                (),
                {
                    "symbols": "WLD",
                    "venue": "bitvavo",
                    "interval": "4h",
                    "start_ts": None,
                    "end_ts": None,
                    "breadth_scope": "selected",
                },
            )(),
            rows=[],
            measures={"breath_phase_distribution": {}, "breath_alignment_distribution": {}, "symbol_regime_distribution": {}, "quality_state_distribution": {}},
            output_paths={},
        )
        self.assertEqual(manifest["safety_markers"], SAFETY_MARKERS)

    def test_print_summary_smoke(self) -> None:
        row = build_recomputed_row(
            {
                "symbol": "WLD",
                "venue": "bitvavo",
                "interval_code": "4h",
                "asof_ts_utc": "2026-05-01T00:00:00Z",
                "market_breath_phase": "EXHALE_EXPANSION",
                "market_breath_state": "CONFIRMED",
                "relative_strength_score": 30.0,
                "momentum_score": 25.0,
                "btc_alignment_score": 12.0,
                "breadth_alignment_score": 5.0,
                "market_breath_confidence": 100.0,
            }
        )
        print_summary(
            rows=[row],
            measures={
                "breath_phase_distribution": {"EXPANSION": 1},
                "breath_alignment_distribution": {"ALIGNED": 1},
                "symbol_regime_distribution": {"REL_STRENGTH": 1},
                "quality_state_distribution": {"HIGH": 1},
            },
        )

    def test_breadth_dummy_rows_use_nonselected_full_universe_returns(self) -> None:
        from datetime import datetime, timedelta

        base = datetime(2026, 5, 1, 0, 0)
        times = [base + timedelta(hours=4 * i) for i in range(7)]
        history = {
            1: (times, [100.0] * 7),
            2: (times, [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0]),
            3: (times, [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 90.0]),
        }
        rows = breadth_dummy_rows_at_asof(history, asof_ts=times[-1], exclude_asset_ids={1})
        self.assertEqual(len(rows), 2)
        returns = sorted(round(row["return_6"], 6) for row in rows)
        self.assertEqual(returns, [-10.0, 10.0])

    def test_requested_btc_is_preserved_as_output_asset(self) -> None:
        from src.research.run_market_breath_analysis_v1 import Asset
        import unittest.mock as mock

        assets = [Asset(asset_id=1, symbol="BTC"), Asset(asset_id=2, symbol="ETH")]
        with mock.patch("src.research.run_historical_market_breath_source_recompute_v1.fetch_assets", return_value=assets):
            selected, btc = resolve_assets(object(), requested_symbols=["BTC", "ETH"])
        self.assertEqual([asset.symbol for asset in selected], ["BTC", "ETH"])
        self.assertEqual(btc.symbol, "BTC")

    def test_main_emits_failed_once_without_traceback(self) -> None:
        from unittest.mock import patch
        from src.research import run_historical_market_breath_source_recompute_v1 as mod
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "get_connection", side_effect=RuntimeError("boom")):
                with patch("builtins.print") as mocked_print:
                    rc = mod.main(["--symbols", "BTC", "--max-rows", "1", "--output-dir", tmp])
        self.assertEqual(rc, 1)
        terminal = [str(call) for call in mocked_print.call_args_list if "FAILED runner=" in str(call) or "INTERRUPTED runner=" in str(call) or "FINISHED runner=" in str(call)]
        self.assertEqual(len(terminal), 1)
        self.assertIn("FAILED runner=", terminal[0])

    def test_main_emits_interrupted_once_and_restores_handlers(self) -> None:
        import signal
        from unittest.mock import patch
        from src.research import run_historical_market_breath_source_recompute_v1 as mod
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "get_connection", side_effect=mod._RunnerInterrupted(signal.SIGTERM)):
                with patch("builtins.print") as mocked_print:
                    rc = mod.main(["--symbols", "BTC", "--max-rows", "1", "--output-dir", tmp])
            checkpoint = json.loads((Path(tmp) / mod.CHECKPOINT_JSON).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["terminal_state"], "INTERRUPTED")
            self.assertEqual(checkpoint["rows_written"], 0)
        self.assertEqual(rc, 130)
        terminal = [str(call) for call in mocked_print.call_args_list if "FAILED runner=" in str(call) or "INTERRUPTED runner=" in str(call) or "FINISHED runner=" in str(call)]
        self.assertEqual(len(terminal), 1)
        self.assertIn("INTERRUPTED runner=", terminal[0])
        for sig, handler in previous.items():
            self.assertIs(signal.getsignal(sig), handler)

    def test_interrupted_run_resumes_from_next_checkpointed_timestamp(self) -> None:
        from datetime import datetime
        from types import SimpleNamespace
        from unittest.mock import patch
        from src.research import run_historical_market_breath_source_recompute_v1 as mod

        first_row = {"symbol": "BTC", "asof_ts_utc": "2026-01-01T00:00:00Z"}
        second_row = {"symbol": "BTC", "asof_ts_utc": "2026-01-01T04:00:00Z"}
        first_ts = datetime(2026, 1, 1, 0, 0)
        second_ts = datetime(2026, 1, 1, 4, 0)

        def interrupted_recompute(**kwargs):
            kwargs["checkpoint_callback"](1, first_ts, [first_row], 1)
            raise mod._RunnerInterrupted(mod.signal.SIGTERM)

        def resumed_recompute(**kwargs):
            self.assertEqual(kwargs["start_timestamp_index"], 1)
            self.assertEqual(kwargs["initial_rows"], [first_row])
            kwargs["checkpoint_callback"](2, second_ts, [second_row], 2)
            return [first_row, second_row], {}

        with tempfile.TemporaryDirectory() as tmp:
            conn = SimpleNamespace(close=lambda: None)
            with patch.object(mod, "get_connection", return_value=conn), patch.object(mod, "recompute_rows", side_effect=interrupted_recompute), patch("builtins.print"):
                rc1 = mod.main(["--symbols", "BTC", "--output", "json", "--output-dir", tmp])
            self.assertEqual(rc1, 130)
            cp1 = json.loads((Path(tmp) / mod.CHECKPOINT_JSON).read_text(encoding="utf-8"))
            self.assertEqual(cp1["timestamps_completed"], 1)
            self.assertEqual(cp1["rows_written"], 1)

            with patch.object(mod, "get_connection", return_value=conn), patch.object(mod, "recompute_rows", side_effect=resumed_recompute), patch("builtins.print"):
                rc2 = mod.main(["--symbols", "BTC", "--output", "json", "--output-dir", tmp, "--resume"])
            self.assertEqual(rc2, 0)
            cp2 = json.loads((Path(tmp) / mod.CHECKPOINT_JSON).read_text(encoding="utf-8"))
            self.assertEqual(cp2["terminal_state"], "FINISHED")
            self.assertEqual(cp2["timestamps_completed"], 2)
            self.assertEqual(cp2["rows_written"], 2)
            partial = [json.loads(line) for line in (Path(tmp) / mod.PARTIAL_ROWS_JSONL).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(partial, [first_row, second_row])

    def test_partial_rows_reconcile_to_checkpoint_boundary(self) -> None:
        from src.research import run_historical_market_breath_source_recompute_v1 as mod
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / mod.PARTIAL_ROWS_JSONL
            path.write_text('\n'.join(json.dumps({"i": i}) for i in range(3)) + '\n', encoding='utf-8')
            rows = mod._read_checkpointed_rows(path, 2)
            self.assertEqual(rows, [{"i": 0}, {"i": 1}])
            self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()), 2)

    def test_resume_identity_mismatch_fails_closed(self) -> None:
        from src.research import run_historical_market_breath_source_recompute_v1 as mod
        with self.assertRaisesRegex(ValueError, "resume identity mismatch"):
            mod._validate_checkpoint_identity({"runner": REPORT_NAME, "interval": "1h"}, {"runner": REPORT_NAME, "interval": "4h"})

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

    def test_no_db_writes(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn(".commit(", text)
        self.assertNotIn("INSERT INTO", text.upper())
        self.assertNotIn("UPDATE ", text.upper())
        self.assertNotIn("DELETE FROM", text.upper())


if __name__ == "__main__":
    unittest.main()
