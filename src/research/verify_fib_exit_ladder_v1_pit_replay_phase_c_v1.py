"""Independent immutable verifier for #707 Phase C PIT replay evidence.

The verifier intentionally contains the small frozen disposition/config surface it
needs instead of importing mutable Phase A classifier code. Its only evidence input
is the SHA-pinned raw Phase C replay JSON.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PATH = REPO_ROOT / "data/research/fib_exit_ladder_v1_pit_replay/pit-replay.json"
RAW_SHA256 = "0eab3c255e56ce49fa3265ab5f4e889e05886b0ee617038a6ce28578d5e80578"
METHODOLOGY_VERSION = "FIB_EXIT_LADDER_V1_PIT_REPLAY_CONTRACT_V1"
CODE_COMMIT_SHA = "3d355648dc6bffaa196580740de369b63aed7459"
EXPECTED_SYMBOLS = ("LINK", "XLM", "SOL", "XRP", "HOT")
FAMILY_ORDER = ("PRO_3X4X", "SUPERCYCLE", "EXPLOSIVE_SUPERCYCLE")
SELL_FRACTION_ORDER = ("0.40", "0.50", "0.60", "0.70", "0.80")

# Frozen #707 §9 outcome semantics and original assignments. These values are
# duplicated deliberately so verification cannot drift when another module changes.
OUTCOME_VALIDATED = "VALIDATED"
OUTCOME_REVISED = "REVISED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
OUTCOME_BLOCKED = "BLOCKED"
OUTCOME_ORDER = (
    OUTCOME_BLOCKED,
    OUTCOME_INSUFFICIENT_DATA,
    OUTCOME_REJECTED,
    OUTCOME_REVISED,
    OUTCOME_VALIDATED,
)
ORIGINAL_ASSET_CONFIG = {
    "LINK": ("PRO_3X4X", "0.80"),
    "XLM": ("PRO_3X4X", "0.80"),
    "SOL": ("SUPERCYCLE", "0.80"),
    "XRP": ("SUPERCYCLE", "0.80"),
    "HOT": ("EXPLOSIVE_SUPERCYCLE", "0.40"),
}


@dataclass(frozen=True)
class VerifiedAsset:
    symbol: str
    selected_target_family: str
    selected_max_ladder_sell_fraction: str
    selection_window_alpha_vs_hold_pct: str
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
    family_index = FAMILY_ORDER.index(row["target_family"])
    return (
        Decimal(row["total_return_pct_with_remaining"]),
        -Decimal(row["max_ladder_sell_fraction"]),
        -family_index,
    )


def _derive_selected_row(asset: dict) -> dict:
    rows = asset["selection_grid_rows"]
    if len(rows) != len(FAMILY_ORDER) * len(SELL_FRACTION_ORDER):
        raise ValueError(f"{asset['symbol']}: expected 15 selection rows, got {len(rows)}")

    seen = {(row["target_family"], row["max_ladder_sell_fraction"]) for row in rows}
    expected = {(family, fraction) for family in FAMILY_ORDER for fraction in SELL_FRACTION_ORDER}
    if seen != expected:
        raise ValueError(f"{asset['symbol']}: incomplete/duplicate frozen selection grid")

    ok_rows = [row for row in rows if row["status"] == "OK"]
    if not ok_rows:
        raise ValueError(f"{asset['symbol']}: no evaluable selection row")
    best = max(ok_rows, key=_selection_key)
    for required in (
        "total_return_pct_with_remaining",
        "hold_return_pct",
        "alpha_vs_hold_pct",
    ):
        if best.get(required) is None:
            raise ValueError(f"{asset['symbol']}: selected row missing {required}")

    # Do not trust a precomputed alpha blindly. Re-derive it from the selected raw row.
    total_return = Decimal(best["total_return_pct_with_remaining"])
    hold_return = Decimal(best["hold_return_pct"])
    alpha = Decimal(best["alpha_vs_hold_pct"])
    if alpha != total_return - hold_return:
        raise ValueError(f"{asset['symbol']}: selected row alpha is inconsistent with raw returns")
    return best


def _validate_runner_selected_policy(asset: dict, selected_row: dict) -> None:
    selected = asset["selected_policy"]
    if selected is None:
        raise ValueError(f"{asset['symbol']}: runner selected_policy missing")
    if (
        selected["target_family"] != selected_row["target_family"]
        or selected["max_ladder_sell_fraction"] != selected_row["max_ladder_sell_fraction"]
    ):
        raise ValueError(f"{asset['symbol']}: runner selected policy does not match raw selection grid")
    if Decimal(selected["selection_metric_value"]) != Decimal(
        selected_row["total_return_pct_with_remaining"]
    ):
        raise ValueError(f"{asset['symbol']}: runner selection metric does not match selected raw row")


def _validate_oos_policy(asset: dict, family: str, fraction: str) -> None:
    for key in ("oos_window_1", "oos_window_2"):
        row = asset[key]
        if row is None:
            continue
        if row["target_family"] != family or row["max_ladder_sell_fraction"] != fraction:
            raise ValueError(f"{asset['symbol']}: {key} retuned away from frozen selection")


def _pit_disposition(asset: dict, selected_row: dict) -> str:
    """Apply frozen #707 §9 semantics using only raw Phase C evidence."""
    if asset["status"] != "OK" or asset["selected_policy"] is None:
        return OUTCOME_INSUFFICIENT_DATA

    oos = [asset["oos_window_1"], asset["oos_window_2"]]
    evaluable = [row for row in oos if row is not None and row["status"] == "OK"]
    if not evaluable:
        return OUTCOME_INSUFFICIENT_DATA

    oos_positive = [Decimal(row["alpha_vs_hold_pct"]) > 0 for row in evaluable]
    if all(oos_positive):
        return OUTCOME_VALIDATED
    if not any(oos_positive):
        return OUTCOME_REJECTED

    # Mixed OOS evidence reuses #270's majority-sign rule. The evaluated sign
    # set is the frozen selection-window policy plus the two evaluable OOS
    # windows. Crucially, selection sign comes from the selected grid row's
    # actual alpha, never from selection_metric_value (which is total return).
    selection_positive = Decimal(selected_row["alpha_vs_hold_pct"]) > 0
    sign_votes = [selection_positive, *oos_positive]
    positive_count = sum(1 for value in sign_votes if value)
    if positive_count > len(sign_votes) / 2:
        return OUTCOME_REVISED
    return OUTCOME_REJECTED


def _overall_disposition(assets: list[VerifiedAsset]) -> str:
    symbols = [asset.symbol for asset in assets]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate asset in verified disposition set")
    unexpected = sorted(set(symbols) - set(EXPECTED_SYMBOLS))
    if unexpected:
        raise ValueError(f"unexpected verified assets: {unexpected}")
    missing = set(EXPECTED_SYMBOLS) - set(symbols)
    outcomes = [asset.outcome for asset in assets] + [OUTCOME_INSUFFICIENT_DATA for _ in missing]
    return min(outcomes, key=OUTCOME_ORDER.index)


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
        selected_row = _derive_selected_row(asset)
        family = selected_row["target_family"]
        fraction = selected_row["max_ladder_sell_fraction"]
        _validate_runner_selected_policy(asset, selected_row)
        _validate_oos_policy(asset, family, fraction)

        outcome = _pit_disposition(asset, selected_row)
        oos1 = asset["oos_window_1"]
        oos2 = asset["oos_window_2"]
        verified.append(
            VerifiedAsset(
                symbol=symbol,
                selected_target_family=family,
                selected_max_ladder_sell_fraction=fraction,
                selection_window_alpha_vs_hold_pct=selected_row["alpha_vs_hold_pct"],
                oos_window_1_alpha_vs_hold_pct=(
                    oos1["alpha_vs_hold_pct"] if oos1 is not None else "NaN"
                ),
                oos_window_2_alpha_vs_hold_pct=(
                    oos2["alpha_vs_hold_pct"] if oos2 is not None else "NaN"
                ),
                outcome=outcome,
            )
        )

    overall = _overall_disposition(verified)

    original_vs_selected = {}
    for item in verified:
        original_family, original_fraction = ORIGINAL_ASSET_CONFIG[item.symbol]
        original_vs_selected[item.symbol] = {
            "original_target_family": original_family,
            "original_max_ladder_sell_fraction": original_fraction,
            "selected_target_family": item.selected_target_family,
            "selected_max_ladder_sell_fraction": item.selected_max_ladder_sell_fraction,
            "assignment_changed": (
                item.selected_target_family != original_family
                or item.selected_max_ladder_sell_fraction != original_fraction
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
        "methodology_promotion_grade": 0,
        "promotion_eligible": False,
        "promotion_blocker": "POSITIVE_OOS_ALPHA_NOT_MET",
    }


def main() -> int:
    print(json.dumps(verify_evidence(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
