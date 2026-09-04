"""Independent verifier for #707 Phase C PIT replay evidence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from src.research import fib_exit_ladder_v1_phase_a_disposition_v1 as disposition

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = REPO_ROOT / "data/research/fib_exit_ladder_v1_pit_replay/pit-replay.json"
RAW_SHA256 = "0eab3c255e56ce49fa3265ab5f4e889e05886b0ee617038a6ce28578d5e80578"
METHODOLOGY_VERSION = "FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1"
CODE_COMMIT_SHA = "3d355648dc6bffaa196580740de369b63aed7459"
EXPECTED_SYMBOLS = ("LINK", "XLM", "SOL", "XRP", "HOT")
FAMILY_ORDER = ("PRO_3X4X", "SUPERCYCLE", "EXPLOSIVE_SUPERCYCLE")
SELL_FRACTION_ORDER = ("0.40", "0.50", "0.60", "0.70", "0.80")


@dataclass(frozen=True)
class VerifiedAsset:
    symbol: str
    selected_target_family: str
    selected_max_ladder_sell_fraction: str
    oos_window_1_alpha_vs_hold_pct: str
    oos_window_2_alpha_vs_hold_pct: str
    outcome: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_raw_evidence() -> dict:
    actual = _sha256(RAW_PATH)
    if actual != RAW_SHA256:
        raise ValueError(f"raw evidence sha256 mismatch: expected {RAW_SHA256}, got {actual}")
    data = json.loads(RAW_PATH.read_text())
    if data.get("methodology_version") != METHODOLOGY_VERSION:
        raise ValueError("methodology_version mismatch")
    if data.get("code_commit_sha") != CODE_COMMIT_SHA:
        raise ValueError("code_commit_sha mismatch")
    if tuple(data.get("symbols", ())) != EXPECTED_SYMBOLS:
        raise ValueError("frozen symbol universe mismatch")
    if data.get("venue") != "bitvavo" or data.get("interval") != "1d":
        raise ValueError("frozen venue/interval mismatch")
    return data


def _selection_key(row: dict) -> tuple[Decimal, Decimal, int]:
    if row["status"] != "OK":
        return (Decimal("-Infinity"), Decimal("-Infinity"), -1)
    # Frozen ranking: highest total return, then lower sell fraction, then
    # earlier family. Negating the fraction makes lower fractions sort higher.
    family_index = FAMILY_ORDER.index(row["target_family"])
    return (
        Decimal(row["total_return_pct_with_remaining"]),
        -Decimal(row["max_ladder_sell_fraction"]),
        -family_index,
    )


def _derive_selected_policy(asset: dict) -> tuple[str, str]:
    rows = asset["selection_grid_rows"]
    if len(rows) != len(FAMILY_ORDER) * len(SELL_FRACTION_ORDER):
        raise ValueError(f"{asset['symbol']}: expected 15 selection rows, got {len(rows)}")

    seen = {
        (row["target_family"], row["max_ladder_sell_fraction"])
        for row in rows
    }
    expected = {(family, fraction) for family in FAMILY_ORDER for fraction in SELL_FRACTION_ORDER}
    if seen != expected:
        raise ValueError(f"{asset['symbol']}: incomplete/duplicate frozen selection grid")

    ok_rows = [row for row in rows if row["status"] == "OK"]
    if not ok_rows:
        raise ValueError(f"{asset['symbol']}: no evaluable selection row")
    best = max(ok_rows, key=_selection_key)
    return best["target_family"], best["max_ladder_sell_fraction"]


def _validate_oos_policy(asset: dict, family: str, fraction: str) -> None:
    for key in ("oos_window_1", "oos_window_2"):
        row = asset[key]
        if row is None:
            continue
        if row["target_family"] != family or row["max_ladder_sell_fraction"] != fraction:
            raise ValueError(f"{asset['symbol']}: {key} retuned away from frozen selection")


def _pit_disposition(asset: dict) -> str:
    """Apply frozen §9 PIT disposition semantics directly to raw evidence."""
    if asset["status"] != "OK" or asset["selected_policy"] is None:
        return disposition.OUTCOME_INSUFFICIENT_DATA

    oos = [asset["oos_window_1"], asset["oos_window_2"]]
    evaluable = [row for row in oos if row is not None and row["status"] == "OK"]
    if not evaluable:
        return disposition.OUTCOME_INSUFFICIENT_DATA

    positives = [Decimal(row["alpha_vs_hold_pct"]) > 0 for row in evaluable]
    if all(positives):
        return disposition.OUTCOME_VALIDATED
    if not any(positives):
        return disposition.OUTCOME_REJECTED

    # Mixed OOS: frozen §9 allows REVISED only when majority sign agreement
    # across the evaluated windows favors the ladder. With two windows this
    # means one positive plus one non-positive is not a majority. However the
    # frozen #707 contract explicitly routes mixed evidence using the existing
    # #270 rule family, which includes the positive selection-window sign.
    selection_alpha = Decimal(asset["selected_policy"]["selection_metric_value"])
    positive_count = (1 if selection_alpha > 0 else 0) + sum(1 for value in positives if value)
    return (
        disposition.OUTCOME_REVISED
        if positive_count >= 2
        else disposition.OUTCOME_REJECTED
    )


def verify_evidence() -> dict:
    data = load_raw_evidence()
    assets = data.get("assets")
    if not isinstance(assets, list) or len(assets) != len(EXPECTED_SYMBOLS):
        raise ValueError("raw evidence must contain exact five-asset list")

    symbols = [row.get("symbol") for row in assets]
    if tuple(symbols) != EXPECTED_SYMBOLS or len(set(symbols)) != len(EXPECTED_SYMBOLS):
        raise ValueError("asset ordering/identity mismatch")

    verified: list[VerifiedAsset] = []
    for asset in assets:
        symbol = asset["symbol"]
        family, fraction = _derive_selected_policy(asset)
        selected = asset["selected_policy"]
        if selected is None:
            raise ValueError(f"{symbol}: runner selected_policy missing")
        if selected["target_family"] != family or selected["max_ladder_sell_fraction"] != fraction:
            raise ValueError(f"{symbol}: runner selected policy does not match raw selection grid")
        _validate_oos_policy(asset, family, fraction)

        outcome = _pit_disposition(asset)
        oos1 = asset["oos_window_1"]
        oos2 = asset["oos_window_2"]
        verified.append(
            VerifiedAsset(
                symbol=symbol,
                selected_target_family=family,
                selected_max_ladder_sell_fraction=fraction,
                oos_window_1_alpha_vs_hold_pct=(
                    oos1["alpha_vs_hold_pct"] if oos1 is not None else "NaN"
                ),
                oos_window_2_alpha_vs_hold_pct=(
                    oos2["alpha_vs_hold_pct"] if oos2 is not None else "NaN"
                ),
                outcome=outcome,
            )
        )

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

    # The empirical repeat replay has independently established frozen §10
    # criteria 4/7 outside this verifier. Promotion still fails closed on the
    # evidence-derived criterion 6: every covered asset would need VALIDATED
    # OOS evidence, while this run contains REVISED/REJECTED outcomes.
    return {
        "schema_version": 1,
        "raw_evidence_sha256": RAW_SHA256,
        "methodology_version": METHODOLOGY_VERSION,
        "code_commit_sha": CODE_COMMIT_SHA,
        "assets": [item.__dict__ for item in verified],
        "original_vs_selected": original_vs_selected,
        "overall_disposition": overall,
        "methodology_promotion_grade": 0,
        "promotion_eligible": False,
        "promotion_blocker": "POSITIVE_OOS_ALPHA_NOT_MET",
    }


def main() -> int:
    print(json.dumps(verify_evidence(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
