from __future__ import annotations

"""Deterministic verifier for #707 Phase C PIT Fib exit-ladder evidence.

Research-only. Reads the committed raw evidence file, independently re-derives
selection and dispositions under the frozen v1 PIT contract, and fails closed
on provenance/schema/scope drift. No DB, account, broker, decision_gate,
execution_planner, executor, profile, or runtime access.
"""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.research import fib_exit_ladder_v1_phase_a_disposition_v1 as disposition
from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as contract

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = REPO_ROOT / "data/research/fib_exit_ladder_v1_pit_replay/pit-replay.json"
RAW_SHA256 = "0eab3c255e56ce49fa3265ab5f4e889e05886b0ee617038a6ce28578d5e80578"
METHODOLOGY_VERSION = "FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1"
CODE_COMMIT_SHA = "3d355648dc6bffaa196580740de369b63aed7459"
FAMILY_ORDER = ("PRO_3X4X", "SUPERCYCLE", "EXPLOSIVE_SUPERCYCLE")
EXPECTED_SYMBOLS = tuple(contract.REQUIRED_ASSET_UNIVERSE)
EXPECTED_WINDOWS = {
    "SELECTION_WINDOW": contract.SELECTION_WINDOW,
    "OOS_WINDOW_1": contract.OOS_WINDOW_1,
    "OOS_WINDOW_2": contract.OOS_WINDOW_2,
}


@dataclass(frozen=True)
class VerifiedAsset:
    symbol: str
    selected_target_family: str | None
    selected_max_ladder_sell_fraction: str | None
    selection_alpha_vs_hold_pct: str | None
    oos_window_1_status: str | None
    oos_window_1_alpha_vs_hold_pct: str | None
    oos_window_2_status: str | None
    oos_window_2_alpha_vs_hold_pct: str | None
    outcome: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def load_raw_evidence(path: Path = RAW_PATH) -> dict[str, Any]:
    _require(path.exists(), f"raw evidence not found: {path}")
    actual_sha = _sha256(path)
    _require(actual_sha == RAW_SHA256, f"raw evidence sha256 mismatch: {actual_sha}")
    data = json.loads(path.read_text(encoding="utf-8"))
    _validate_top_level(data)
    return data


def _validate_top_level(data: dict[str, Any]) -> None:
    _require(data.get("schema_version") == 1, "unexpected evidence schema_version")
    _require(data.get("methodology_version") == METHODOLOGY_VERSION, "methodology_version mismatch")
    _require(data.get("code_commit_sha") == CODE_COMMIT_SHA, "code_commit_sha mismatch")
    _require(data.get("venue") == "bitvavo", "venue mismatch")
    _require(data.get("interval") == "1d", "interval mismatch")
    _require(tuple(data.get("symbols", [])) == EXPECTED_SYMBOLS, "frozen symbol universe mismatch")
    _require(data.get("methodology_promotion_grade") == 0, "raw runner must remain promotion_grade=0")
    _require(data.get("promotion_eligible") is False, "raw runner must remain promotion_eligible=false")

    windows = data.get("windows")
    _require(isinstance(windows, dict), "windows must be an object")
    for label, (from_ts, to_ts) in EXPECTED_WINDOWS.items():
        row = windows.get(label)
        _require(isinstance(row, dict), f"missing window metadata: {label}")
        _require(row.get("from_ts") == from_ts, f"{label} from_ts mismatch")
        _require(row.get("to_ts") == to_ts, f"{label} to_ts mismatch")

    _require(tuple(data.get("candidate_families", [])) == FAMILY_ORDER, "candidate family order mismatch")
    _require(
        tuple(data.get("sell_fraction_grid", [])) == ("0.40", "0.50", "0.60", "0.70", "0.80"),
        "sell fraction grid mismatch",
    )


def _derive_selected_grid_row(asset: dict[str, Any]) -> dict[str, Any] | None:
    rows = asset.get("selection_grid_rows")
    _require(isinstance(rows, list), f"{asset.get('symbol')}: selection_grid_rows must be a list")
    expected_count = len(FAMILY_ORDER) * 5
    _require(len(rows) == expected_count, f"{asset.get('symbol')}: expected {expected_count} selection rows")

    eligible = [
        row
        for row in rows
        if row.get("status") == "OK"
        and int(row.get("sample_count", 0)) > 0
        and row.get("total_return_pct_with_remaining") is not None
    ]
    if not eligible:
        return None

    family_rank = {family: index for index, family in enumerate(FAMILY_ORDER)}
    return sorted(
        eligible,
        key=lambda row: (
            -_decimal(row["total_return_pct_with_remaining"]),
            _decimal(row["max_ladder_sell_fraction"]),
            family_rank[row["target_family"]],
        ),
    )[0]


def _assert_runner_selection_matches(asset: dict[str, Any], selected: dict[str, Any] | None) -> None:
    published = asset.get("selected_policy")
    if selected is None:
        _require(published is None, f"{asset['symbol']}: runner selected a policy without eligible selection evidence")
        return
    _require(isinstance(published, dict), f"{asset['symbol']}: selected_policy missing")
    _require(published.get("symbol") == asset["symbol"], f"{asset['symbol']}: selected_policy symbol mismatch")
    _require(published.get("target_family") == selected["target_family"], f"{asset['symbol']}: family selection mismatch")
    _require(
        published.get("max_ladder_sell_fraction") == selected["max_ladder_sell_fraction"],
        f"{asset['symbol']}: fraction selection mismatch",
    )
    _require(
        _decimal(published.get("selection_metric_value")) == _decimal(selected["total_return_pct_with_remaining"]),
        f"{asset['symbol']}: selection metric mismatch",
    )
    _require(
        int(published.get("selection_sample_count")) == int(selected.get("sample_count", 0)),
        f"{asset['symbol']}: selection sample count mismatch",
    )


def _oos_evaluable(row: dict[str, Any] | None) -> bool:
    return bool(row and row.get("status") == "OK" and int(row.get("sample_count", 0)) > 0)


def _derive_outcome(asset: dict[str, Any], selected: dict[str, Any] | None) -> str:
    if selected is None:
        return disposition.OUTCOME_INSUFFICIENT_DATA

    oos_rows = [asset.get("oos_window_1"), asset.get("oos_window_2")]
    evaluable = [row for row in oos_rows if _oos_evaluable(row)]
    if not evaluable:
        return disposition.OUTCOME_INSUFFICIENT_DATA

    for label, row in zip(("OOS_WINDOW_1", "OOS_WINDOW_2"), oos_rows):
        if not _oos_evaluable(row):
            continue
        _require(row.get("symbol") == asset["symbol"], f"{asset['symbol']}: {label} symbol mismatch")
        _require(row.get("target_family") == selected["target_family"], f"{asset['symbol']}: {label} family retuned")
        _require(
            row.get("max_ladder_sell_fraction") == selected["max_ladder_sell_fraction"],
            f"{asset['symbol']}: {label} fraction retuned",
        )

    positive_oos = sum(_decimal(row["alpha_vs_hold_pct"]) > 0 for row in evaluable)
    if positive_oos == len(evaluable):
        return disposition.OUTCOME_VALIDATED
    if positive_oos == 0:
        return disposition.OUTCOME_REJECTED

    # Frozen §9 explicitly reuses #270 rules 3/4 for mixed OOS evidence.
    # Therefore sign agreement is evaluated across the selection window plus
    # the evaluable OOS windows, with strict alpha > 0 as the favorable sign.
    signs = [_decimal(selected["alpha_vs_hold_pct"]) > 0]
    signs.extend(_decimal(row["alpha_vs_hold_pct"]) > 0 for row in evaluable)
    favorable_majority = sum(signs) > (len(signs) / 2)
    return disposition.OUTCOME_REVISED if favorable_majority else disposition.OUTCOME_REJECTED


def verify_asset(asset: dict[str, Any]) -> VerifiedAsset:
    symbol = asset.get("symbol")
    _require(symbol in EXPECTED_SYMBOLS, f"unexpected asset symbol: {symbol}")
    counts = asset.get("candle_row_counts")
    _require(isinstance(counts, dict), f"{symbol}: candle_row_counts missing")
    _require(set(counts) == set(EXPECTED_WINDOWS), f"{symbol}: candle row-count windows mismatch")
    _require(all(isinstance(value, int) and value >= 0 for value in counts.values()), f"{symbol}: invalid candle counts")

    selected = _derive_selected_grid_row(asset)
    _assert_runner_selection_matches(asset, selected)
    outcome = _derive_outcome(asset, selected)

    oos1 = asset.get("oos_window_1")
    oos2 = asset.get("oos_window_2")
    return VerifiedAsset(
        symbol=symbol,
        selected_target_family=selected.get("target_family") if selected else None,
        selected_max_ladder_sell_fraction=selected.get("max_ladder_sell_fraction") if selected else None,
        selection_alpha_vs_hold_pct=selected.get("alpha_vs_hold_pct") if selected else None,
        oos_window_1_status=oos1.get("status") if isinstance(oos1, dict) else None,
        oos_window_1_alpha_vs_hold_pct=oos1.get("alpha_vs_hold_pct") if isinstance(oos1, dict) else None,
        oos_window_2_status=oos2.get("status") if isinstance(oos2, dict) else None,
        oos_window_2_alpha_vs_hold_pct=oos2.get("alpha_vs_hold_pct") if isinstance(oos2, dict) else None,
        outcome=outcome,
    )


def verify_evidence(path: Path = RAW_PATH) -> dict[str, Any]:
    data = load_raw_evidence(path)
    assets = data.get("assets")
    _require(isinstance(assets, list), "assets must be a list")
    symbols = [asset.get("symbol") for asset in assets]
    _require(len(symbols) == len(set(symbols)), "duplicate asset rows")
    _require(tuple(symbols) == EXPECTED_SYMBOLS, "assets must match frozen universe and order")

    verified = [verify_asset(asset) for asset in assets]
    phase_a_shape = [
        disposition.AssetDisposition(item.symbol, item.outcome, None)
        for item in verified
    ]
    overall = disposition.overall_disposition(phase_a_shape)

    original_vs_selected = {}
    for item in verified:
        original = disposition.original_config_for_asset(item.symbol)
        original_vs_selected[item.symbol] = {
            "original_target_family": original.target_family,
            "original_max_ladder_sell_fraction": format(original.max_ladder_sell_fraction, "f"),
            "selected_target_family": item.selected_target_family,
            "selected_max_ladder_sell_fraction": item.selected_max_ladder_sell_fraction,
            "assignment_changed": (
                item.selected_target_family != original.target_family
                or item.selected_max_ladder_sell_fraction != format(original.max_ladder_sell_fraction, "f")
            ),
        }

    return {
        "schema_version": 1,
        "raw_evidence_sha256": RAW_SHA256,
        "methodology_version": METHODOLOGY_VERSION,
        "code_commit_sha": CODE_COMMIT_SHA,
        "assets": [item.__dict__ for item in verified],
        "original_vs_selected": original_vs_selected,
        "overall_disposition": overall,
        # Criteria 4/7 require an empirical second replay against the same
        # underlying data. The verifier intentionally cannot self-certify it.
        "methodology_promotion_grade": 0,
        "promotion_eligible": False,
        "promotion_blocker": "EMPIRICAL_REPEAT_REPLAY_REQUIRED",
    }


def main() -> int:
    print(json.dumps(verify_evidence(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
