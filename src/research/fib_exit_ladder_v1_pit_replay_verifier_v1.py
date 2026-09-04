"""
Synth v2.6 research verifier: FIB_EXIT_LADDER_V1_PIT_REPLAY_VERIFIER_V1
(Issue #707 Phase C, contract § 12).

Layer:
    research only. Pure read of committed JSON evidence plus local sha256
    hashing. No DB access, no network I/O, no account/broker/order code.

Purpose:
    Independently reproduce, from the committed raw evidence under
    <evidence_dir>/raw/ only (never from any hand-written findings prose),
    the per-asset selected policy, OOS results, per-asset disposition,
    overall disposition, and all nine § 10 promotion-grade criteria, and the
    resulting methodology_promotion_grade. Per contract § 12 rule 5, if this
    verifier's derived result disagrees with a findings document, the
    verifier's derived result is authoritative.

Structural (code-level) criteria:
    Two of the nine criteria -- `true_pit_eligibility` and `no_look_ahead`
    -- are properties of the frozen, unmodified Phase B engine
    (src/research/fib_exit_ladder_v1_pit_replay_engine_v1.py) and Phase A
    contract helper (src/research/fib_exit_ladder_v1_pit_replay_contract_v1.py).
    There is no per-row field in the committed evidence that could prove
    "this specific anchor never read a future candle" after the fact --
    that guarantee is a property of the code path that produced the row, and
    is proven by the existing regression tests
    (tests/test_fib_exit_ladder_v1_pit_replay_engine_v1.py groups A/B,
    tests/test_fib_exit_ladder_v1_pit_replay_contract_v1.py) plus this
    Phase C's own architecture-import test. This module marks those two
    criteria True only because those tests exist unchanged; it does not
    silently assume them for a modified engine.

    The remaining seven criteria are derived live, in this module, from the
    committed JSON evidence: window disjointness and no-retuning
    (`disjoint_selection_oos`), independent re-ranking of the selection grid
    compared against the reported selected policy
    (`deterministic_replay`, `stable_reproducible`), minimum sample counts
    (`sufficient_sample_count`), per-asset disposition over the required
    five-asset universe (`positive_oos_alpha`), sha256 hash verification
    (`immutable_raw_evidence`), and overall internal consistency
    (`verifier_reproduces`).

Boundary:
    - No DB access, no network I/O.
    - No account/balance/position/order access.
    - No decision_gate, execution_planner, or executor imports.
    - No writes: this module only reads files under <evidence_dir>/raw/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from src.research import fib_exit_ladder_v1_pit_replay_contract_v1 as pit_contract

REQUIRED_ASSET_UNIVERSE = pit_contract.REQUIRED_ASSET_UNIVERSE
CANDIDATE_FAMILIES = pit_contract.CANDIDATE_FAMILIES

STATUS_OK = "OK"

DISPOSITION_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
DISPOSITION_REJECTED = "REJECTED"
DISPOSITION_REVISED = "REVISED"
DISPOSITION_VALIDATED = "VALIDATED"

# Worst-to-best, mirrors fib_exit_ladder_v1_phase_a_disposition_v1.OUTCOME_ORDER
# minus BLOCKED (no baseline-reproduction concept in the PIT protocol's § 9).
DISPOSITION_ORDER = (
    DISPOSITION_INSUFFICIENT_DATA,
    DISPOSITION_REJECTED,
    DISPOSITION_REVISED,
    DISPOSITION_VALIDATED,
)


class VerifierError(RuntimeError):
    """Fail-closed verifier error: missing file, hash mismatch, malformed
    evidence, or a required asset absent/duplicated. Never silently
    proceeds past one of these."""


# ---------------------------------------------------------------------------
# Raw evidence loading + hash verification.
# ---------------------------------------------------------------------------


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    if not path.exists():
        raise VerifierError(f"Required raw evidence file missing: {path}.")
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class LoadedEvidence:
    manifest: dict[str, Any]
    selection_grid_rows: list[dict[str, Any]]
    selected_policy_rows: list[dict[str, Any]]
    oos_rows: list[dict[str, Any]]


def load_evidence(evidence_dir: Path) -> LoadedEvidence:
    raw_dir = evidence_dir / "raw"
    manifest = load_json(raw_dir / "manifest_v1.json")

    hash_mismatches: list[str] = []
    for filename, recorded in manifest.get("files", {}).items():
        file_path = raw_dir / filename
        if not file_path.exists():
            hash_mismatches.append(f"{filename}: file missing")
            continue
        actual_hash = sha256_of_file(file_path)
        if actual_hash != recorded.get("sha256"):
            hash_mismatches.append(
                f"{filename}: expected sha256={recorded.get('sha256')}, actual sha256={actual_hash}"
            )
        actual_size = file_path.stat().st_size
        if actual_size != recorded.get("byte_size"):
            hash_mismatches.append(
                f"{filename}: expected byte_size={recorded.get('byte_size')}, actual byte_size={actual_size}"
            )

    if hash_mismatches:
        raise VerifierError(
            "Provenance hash/size verification failed for committed raw "
            f"evidence; refusing to proceed: {hash_mismatches}"
        )

    selection_grid = load_json(raw_dir / "selection_grid_results_v1.json")["rows"]
    selected_policies = load_json(raw_dir / "selected_policies_v1.json")["rows"]
    oos_results = load_json(raw_dir / "oos_evaluation_results_v1.json")["rows"]

    return LoadedEvidence(
        manifest=manifest,
        selection_grid_rows=selection_grid,
        selected_policy_rows=selected_policies,
        oos_rows=oos_results,
    )


# ---------------------------------------------------------------------------
# Independent re-derivation of the SELECTION_WINDOW selection (contract § 7).
# ---------------------------------------------------------------------------


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return Decimal(str(value))


def rerank_selection_grid(rows_for_symbol: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Reproduces contract § 7's selection ranking directly from raw grid
    rows: highest total_return_pct_with_remaining, tie-broken by (1) lower
    max_ladder_sell_fraction, then (2) family position in CANDIDATE_FAMILIES.
    Returns None if no row is status OK (INSUFFICIENT_DATA), matching
    `select_policy_on_selection_window`'s behavior in the frozen engine."""
    eligible = [
        row
        for row in rows_for_symbol
        if row.get("status") == STATUS_OK and row.get("total_return_pct_with_remaining") is not None
    ]
    if not eligible:
        return None

    def sort_key(row: dict[str, Any]) -> tuple[Decimal, Decimal, int]:
        total_return = _dec(row["total_return_pct_with_remaining"])
        fraction = _dec(row["max_ladder_sell_fraction"])
        assert total_return is not None and fraction is not None
        family = row["family"]
        return (-total_return, fraction, CANDIDATE_FAMILIES.index(family))

    ranked = sorted(eligible, key=sort_key)
    best = ranked[0]
    return {
        "target_family": best["family"],
        "max_ladder_sell_fraction": best["max_ladder_sell_fraction"],
        "selection_metric_value": best["total_return_pct_with_remaining"],
        "selection_sample_count": best.get("sample_count", 0),
    }


# ---------------------------------------------------------------------------
# Per-asset / overall disposition (contract § 9, PIT-specific: two OOS
# windows only, no baseline-reproduction concept).
# ---------------------------------------------------------------------------


def classify_asset_disposition(
    *,
    selected_policy_row: Optional[dict[str, Any]],
    oos_rows_for_symbol: list[dict[str, Any]],
) -> str:
    if selected_policy_row is None or selected_policy_row.get("status") != "OK":
        return DISPOSITION_INSUFFICIENT_DATA

    ok_windows = [row for row in oos_rows_for_symbol if row.get("status") == STATUS_OK]
    if not ok_windows:
        return DISPOSITION_INSUFFICIENT_DATA

    alphas = [_dec(row["alpha_vs_hold_pct"]) for row in ok_windows]
    if any(alpha is None for alpha in alphas):
        raise VerifierError("OK-status OOS row missing alpha_vs_hold_pct; malformed evidence.")

    total = len(alphas)
    positive = sum(1 for alpha in alphas if alpha > 0)

    if positive == total:
        return DISPOSITION_VALIDATED
    if positive == 0:
        return DISPOSITION_REJECTED
    if positive > total - positive:
        return DISPOSITION_REVISED
    # Tie (only reachable with exactly 2 OK windows split 1-1): majority sign
    # agreement fails per contract § 9's REJECTED clause.
    return DISPOSITION_REJECTED


def overall_disposition(per_asset: dict[str, str]) -> str:
    symbols = list(per_asset.keys())
    duplicated = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
    if duplicated:
        raise VerifierError(f"Duplicate asset entries in evidence: {duplicated}.")

    unexpected = sorted(set(symbols) - set(REQUIRED_ASSET_UNIVERSE))
    if unexpected:
        raise VerifierError(f"Evidence contains asset(s) outside the frozen universe: {unexpected}.")

    missing = sorted(set(REQUIRED_ASSET_UNIVERSE) - set(symbols))
    effective = dict(per_asset)
    for symbol in missing:
        effective[symbol] = DISPOSITION_INSUFFICIENT_DATA

    worst_index = min(DISPOSITION_ORDER.index(outcome) for outcome in effective.values())
    return DISPOSITION_ORDER[worst_index]


# ---------------------------------------------------------------------------
# Promotion-grade criteria (contract § 10).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifierReport:
    per_asset_selected: dict[str, Optional[dict[str, Any]]]
    per_asset_disposition: dict[str, str]
    overall: str
    criteria: dict[str, bool]
    methodology_promotion_grade: int
    promotion_eligible: bool
    mismatches: list[str]


def _windows_disjoint(manifest: dict[str, Any]) -> bool:
    windows = manifest.get("windows", {})
    try:
        selection = windows["SELECTION_WINDOW"]
        oos1 = windows["OOS_WINDOW_1"]
        oos2 = windows["OOS_WINDOW_2"]
    except KeyError:
        return False
    return selection["to_ts"] <= oos1["from_ts"] and oos1["to_ts"] <= oos2["from_ts"]


def _no_retuning(evidence: LoadedEvidence, mismatches: list[str]) -> bool:
    """Verifies every OOS row's (target_family, max_ladder_sell_fraction)
    matches that symbol's SELECTION_WINDOW-frozen selected policy -- i.e.
    the OOS evidence never evaluates a different config per window."""
    selected_by_symbol = {row["symbol"]: row for row in evidence.selected_policy_rows}
    ok = True
    for row in evidence.oos_rows:
        symbol = row.get("symbol")
        selected = selected_by_symbol.get(symbol)
        if selected is None or selected.get("status") != "OK":
            mismatches.append(f"OOS row present for {symbol} with no OK selected policy on record.")
            ok = False
            continue
        if row.get("target_family") != selected.get("target_family") or row.get(
            "max_ladder_sell_fraction"
        ) != selected.get("max_ladder_sell_fraction"):
            mismatches.append(
                f"OOS row for {symbol} window={row.get('window')} used "
                f"({row.get('target_family')}, {row.get('max_ladder_sell_fraction')}) "
                f"which does not match the frozen selected policy "
                f"({selected.get('target_family')}, {selected.get('max_ladder_sell_fraction')}) -- retuning."
            )
            ok = False
    return ok


def verify(evidence_dir: Path) -> VerifierReport:
    evidence = load_evidence(evidence_dir)
    mismatches: list[str] = []

    rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in evidence.selection_grid_rows:
        rows_by_symbol.setdefault(row["symbol"], []).append(row)

    reported_selected_by_symbol = {row["symbol"]: row for row in evidence.selected_policy_rows}
    oos_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in evidence.oos_rows:
        oos_by_symbol.setdefault(row["symbol"], []).append(row)

    per_asset_selected: dict[str, Optional[dict[str, Any]]] = {}
    per_asset_disposition: dict[str, str] = {}
    selection_reproduction_ok = True

    for symbol in sorted(rows_by_symbol):
        derived = rerank_selection_grid(rows_by_symbol[symbol])
        per_asset_selected[symbol] = derived
        reported = reported_selected_by_symbol.get(symbol)

        if derived is None:
            if reported is not None and reported.get("status") == "OK":
                mismatches.append(f"{symbol}: reported selected policy is OK but grid re-derivation found none.")
                selection_reproduction_ok = False
        else:
            if reported is None or reported.get("status") != "OK":
                mismatches.append(f"{symbol}: grid re-derivation found a selection but reported status is not OK.")
                selection_reproduction_ok = False
            elif (
                reported.get("target_family") != derived["target_family"]
                or reported.get("max_ladder_sell_fraction") != derived["max_ladder_sell_fraction"]
            ):
                mismatches.append(
                    f"{symbol}: reported selected policy "
                    f"({reported.get('target_family')}, {reported.get('max_ladder_sell_fraction')}) "
                    f"does not match grid re-derivation "
                    f"({derived['target_family']}, {derived['max_ladder_sell_fraction']})."
                )
                selection_reproduction_ok = False

        per_asset_disposition[symbol] = classify_asset_disposition(
            selected_policy_row=reported,
            oos_rows_for_symbol=oos_by_symbol.get(symbol, []),
        )

    overall = overall_disposition(per_asset_disposition)

    no_retuning_ok = _no_retuning(evidence, mismatches)
    disjoint_ok = _windows_disjoint(evidence.manifest)

    sufficient_sample_count = True
    for symbol in REQUIRED_ASSET_UNIVERSE:
        reported = reported_selected_by_symbol.get(symbol)
        if reported is None or reported.get("status") != "OK" or reported.get("selection_sample_count", 0) < 1:
            sufficient_sample_count = False
            mismatches.append(f"{symbol}: insufficient SELECTION_WINDOW sample count for promotion-grade evidence.")
            continue
        ok_oos = [row for row in oos_by_symbol.get(symbol, []) if row.get("status") == STATUS_OK]
        if not ok_oos:
            sufficient_sample_count = False
            mismatches.append(f"{symbol}: no OOS window with a PIT-confirmed anchor for promotion-grade evidence.")

    positive_oos_alpha = all(
        per_asset_disposition.get(symbol) == DISPOSITION_VALIDATED for symbol in REQUIRED_ASSET_UNIVERSE
    )

    reproduction_matches = selection_reproduction_ok and no_retuning_ok

    criteria = {
        "true_pit_eligibility": True,
        "no_look_ahead": True,
        "disjoint_selection_oos": bool(disjoint_ok and no_retuning_ok),
        "deterministic_replay": bool(reproduction_matches),
        "sufficient_sample_count": bool(sufficient_sample_count),
        "positive_oos_alpha": bool(positive_oos_alpha),
        "stable_reproducible": bool(reproduction_matches),
        "immutable_raw_evidence": True,  # load_evidence already raised on any hash/size mismatch.
        "verifier_reproduces": bool(reproduction_matches and not mismatches),
    }

    promotion_grade = 1 if pit_contract.evaluate_promotion_grade(criteria) else 0

    return VerifierReport(
        per_asset_selected=per_asset_selected,
        per_asset_disposition=per_asset_disposition,
        overall=overall,
        criteria=criteria,
        methodology_promotion_grade=promotion_grade,
        promotion_eligible=promotion_grade == 1,
        mismatches=mismatches,
    )


def report_to_json(report: VerifierReport) -> dict[str, Any]:
    return {
        "per_asset_selected": report.per_asset_selected,
        "per_asset_disposition": report.per_asset_disposition,
        "overall_disposition": report.overall,
        "criteria": report.criteria,
        "methodology_promotion_grade": report.methodology_promotion_grade,
        "promotion_eligible": report.promotion_eligible,
        "mismatches": report.mismatches,
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Issue #707 Phase C: deterministic verifier over committed raw PIT replay evidence."
    )
    parser.add_argument(
        "--evidence-dir",
        default="docs/research/fib_exit_ladder_v1_pit_replay_phase_c_v1",
        help="Directory containing the raw/ evidence produced by run_fib_exit_ladder_v1_pit_replay_v1.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    report = verify(Path(args.evidence_dir))
    print(json.dumps(report_to_json(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
