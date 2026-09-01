"""Independent reproduction of the #270 Phase A disposition from the raw,
committed backtest-sweep JSON artifacts.

Unlike test_fib_exit_ladder_v1_phase_a_evidence_summary_v1.py (which checks
the tracked evidence summary is internally self-consistent), this test does
not trust docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json
as an input to the disposition computation. Instead it:

1. Loads the three raw JSON artifacts committed under
   data/research/fib_exit_ladder_v1_phase_a/ and verifies their sha256
   against the hashes recorded in
   docs/research/fib_exit_ladder_v1_phase_a_provenance_v1.md.
2. Re-derives, from each artifact's `all_rows` (never `best_rows`), the
   exact frozen-config row per asset/window and the rank/sign/window inputs
   the frozen disposition contract needs, independently of the tracked
   evidence summary.
3. Cross-checks those independently derived values against the tracked
   evidence summary (they must agree — the summary must not have drifted
   from the raw artifacts it claims to be derived from).
4. Feeds the independently derived inputs into the unmodified production
   classify_asset_disposition() / overall_disposition() helpers from
   src/research/fib_exit_ladder_v1_phase_a_disposition_v1.py and verifies
   the reported #270 Phase A outcome.

No disposition logic is duplicated here: only the mechanical extraction of
a single row per (symbol, target_family, max_ladder_sell_fraction) from a
flat `all_rows` list, and the input-shape derivation (window OK/alpha-sign
counts, same-fraction family-rank comparison) that the raw sweep does not
already package as classifier input — the classification rules themselves
live exclusively in the imported helpers.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from src.research import fib_exit_ladder_v1_phase_a_disposition_v1 as disposition

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data/research/fib_exit_ladder_v1_phase_a"
PROVENANCE_PATH = REPO_ROOT / "docs/research/fib_exit_ladder_v1_phase_a_provenance_v1.md"
EVIDENCE_SUMMARY_PATH = (
    REPO_ROOT / "docs/research/fib_exit_ladder_v1_phase_a_evidence_summary_v1.json"
)

WINDOW_FILES = {
    "baseline_2020_2022": "baseline_2020_2022.json",
    "validation_2022_2024": "validation_2022_2024.json",
    "validation_2024_2026": "validation_2024_2026.json",
}
VALIDATION_WINDOWS = ("validation_2022_2024", "validation_2024_2026")

PUBLISHED_BASELINE = {
    # From docs/research/fib_exit_ladder_v1_findings.md's published 2021 table.
    "LINK": (Decimal("93.6754"), Decimal("21.5124")),
    "XLM": (Decimal("128.7534"), Decimal("22.8163")),
    "SOL": (Decimal("178.3058"), Decimal("165.8023")),
    "XRP": (Decimal("207.5549"), Decimal("145.9933")),
    "HOT": (Decimal("563.1368"), Decimal("591.5183")),
}

EXPECTED_ASSET_OUTCOMES = {
    "LINK": disposition.OUTCOME_REVISED,
    "XLM": disposition.OUTCOME_REVISED,
    "SOL": disposition.OUTCOME_REVISED,
    "XRP": disposition.OUTCOME_REVISED,
    "HOT": disposition.OUTCOME_REJECTED,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_windows() -> dict:
    return {name: json.loads((RAW_DIR / fname).read_text()) for name, fname in WINDOW_FILES.items()}


def _provenance_sha256_map() -> dict:
    """Parse the `.json` sha256 recorded per window file out of the
    provenance doc's per-artifact tables, without hardcoding a second copy
    of the hashes in this test module."""
    text = PROVENANCE_PATH.read_text()
    result = {}
    for window_name, fname in WINDOW_FILES.items():
        # Row shape: "| sha256 | `<csv-hash>` | `<json-hash>` |" directly
        # below a "| Field | `<...csv>` | `<...json>` |" header row that
        # names this window's files.
        header_pattern = re.compile(
            rf"\| Field \| `{re.escape(fname.replace('.json', '.csv'))}` \| `{re.escape(fname)}` \|\n"
            rf"\|---\|---\|---\|\n"
            rf"\| sha256 \| `([0-9a-f]{{64}})` \| `([0-9a-f]{{64}})` \|"
        )
        match = header_pattern.search(text)
        assert match, f"could not find provenance sha256 row for {fname}"
        result[window_name] = match.group(2)  # JSON column
    return result


def _find_row(all_rows: list[dict], symbol: str, family: str, fraction: str) -> dict:
    matches = [
        row
        for row in all_rows
        if row["symbol"] == symbol
        and row["target_family"] == family
        and row["max_ladder_sell_fraction"] == fraction
    ]
    assert len(matches) == 1, (symbol, family, fraction, len(matches))
    return matches[0]


def _family_rows_same_fraction(all_rows: list[dict], symbol: str, fraction: str) -> dict:
    return {
        row["target_family"]: row
        for row in all_rows
        if row["symbol"] == symbol and row["max_ladder_sell_fraction"] == fraction
    }


def test_committed_raw_artifacts_match_provenance_sha256():
    expected = _provenance_sha256_map()
    for window_name, fname in WINDOW_FILES.items():
        actual = _sha256(RAW_DIR / fname)
        assert actual == expected[window_name], f"{fname} sha256 mismatch vs provenance doc"


def test_committed_raw_artifacts_are_the_frozen_scoreboard_sweep():
    windows = _load_windows()
    for window_name, data in windows.items():
        assert data["runner"] == "run_fib_exit_ladder_scoreboard_v1"
        assert data["venue"] == "bitvavo"
        assert data["interval"] == "1d"
        assert data["rows_total"] == 105
        assert len(data["all_rows"]) == 105


def test_raw_all_rows_reproduce_baseline_against_published_findings():
    windows = _load_windows()
    baseline_rows = windows["baseline_2020_2022"]["all_rows"]
    for symbol, cfg in disposition.ORIGINAL_ASSET_CONFIG.items():
        row = _find_row(baseline_rows, symbol, cfg.target_family, str(cfg.max_ladder_sell_fraction))
        assert row["status"] == "OK"
        published_total, published_hold = PUBLISHED_BASELINE[symbol]
        assert Decimal(row["total_return_pct_with_remaining"]).quantize(Decimal("0.0001")) == published_total
        assert Decimal(row["hold_return_pct"]).quantize(Decimal("0.0001")) == published_hold


def _derive_asset_evidence(windows: dict, symbol: str, cfg) -> dict:
    family, fraction = cfg.target_family, str(cfg.max_ladder_sell_fraction)

    baseline_row = _find_row(windows["baseline_2020_2022"]["all_rows"], symbol, family, fraction)
    baseline_evaluable = baseline_row["status"] == "OK"
    published_total, published_hold = PUBLISHED_BASELINE[symbol]
    baseline_reproduced = None
    if baseline_evaluable:
        baseline_reproduced = (
            Decimal(baseline_row["total_return_pct_with_remaining"]).quantize(Decimal("0.0001")) == published_total
            and Decimal(baseline_row["hold_return_pct"]).quantize(Decimal("0.0001")) == published_hold
        )

    validation_rows = {
        window_name: _find_row(windows[window_name]["all_rows"], symbol, family, fraction)
        for window_name in VALIDATION_WINDOWS
    }
    validation_windows_ok = sum(1 for row in validation_rows.values() if row["status"] == "OK")
    alpha_positive_ok_window_count = sum(
        1
        for row in validation_rows.values()
        if row["status"] == "OK" and Decimal(row["alpha_vs_hold_pct"]) > 0
    )

    all_alphas = []
    if baseline_evaluable:
        all_alphas.append(Decimal(baseline_row["alpha_vs_hold_pct"]))
    all_alphas += [Decimal(row["alpha_vs_hold_pct"]) for row in validation_rows.values() if row["status"] == "OK"]
    bucket_sign_agreement = sum(1 for alpha in all_alphas if alpha > 0) >= 2

    bucket_rank_agreement_all_ok_windows = None
    if alpha_positive_ok_window_count == validation_windows_ok and validation_windows_ok > 0:
        ranked_first_per_window = []
        for window_name, row in validation_rows.items():
            fam_rows = _family_rows_same_fraction(windows[window_name]["all_rows"], symbol, fraction)
            if not all(r["status"] == "OK" for r in fam_rows.values()):
                ranked_first_per_window.append(False)
                continue
            best_value = max(Decimal(r["total_return_pct_with_remaining"]) for r in fam_rows.values())
            ranked_first_per_window.append(
                Decimal(row["total_return_pct_with_remaining"]) == best_value
            )
        bucket_rank_agreement_all_ok_windows = all(ranked_first_per_window)

    return {
        "baseline_evaluable": baseline_evaluable,
        "baseline_reproduced": baseline_reproduced,
        "validation_windows_ok": validation_windows_ok,
        "alpha_positive_ok_window_count": alpha_positive_ok_window_count,
        "bucket_sign_agreement": bucket_sign_agreement,
        "bucket_rank_agreement_all_ok_windows": bucket_rank_agreement_all_ok_windows,
    }


def test_raw_derived_inputs_match_tracked_evidence_summary():
    windows = _load_windows()
    tracked = json.loads(EVIDENCE_SUMMARY_PATH.read_text())
    for symbol, cfg in disposition.ORIGINAL_ASSET_CONFIG.items():
        derived = _derive_asset_evidence(windows, symbol, cfg)
        tracked_asset = tracked["assets"][symbol]
        assert derived["baseline_evaluable"] == tracked_asset["baseline_evaluable"], symbol
        assert derived["baseline_reproduced"] == tracked_asset["baseline_reproduced"], symbol
        assert derived["validation_windows_ok"] == tracked_asset["validation_windows_ok"], symbol
        assert (
            derived["alpha_positive_ok_window_count"] == tracked_asset["alpha_positive_ok_window_count"]
        ), symbol
        assert derived["bucket_sign_agreement"] == tracked_asset["bucket_sign_agreement"], symbol
        assert (
            derived["bucket_rank_agreement_all_ok_windows"]
            == tracked_asset["bucket_rank_agreement_all_ok_windows"]
        ), symbol


def test_raw_artifacts_reproduce_expected_disposition_via_unmodified_helpers():
    windows = _load_windows()
    computed = []
    for symbol, cfg in disposition.ORIGINAL_ASSET_CONFIG.items():
        derived = _derive_asset_evidence(windows, symbol, cfg)
        result = disposition.classify_asset_disposition(
            symbol=symbol,
            baseline_evaluable=derived["baseline_evaluable"],
            baseline_reproduced=derived["baseline_reproduced"],
            has_original_bucket=True,
            validation_windows_ok=derived["validation_windows_ok"],
            validation_windows_total=2,
            alpha_positive_ok_window_count=derived["alpha_positive_ok_window_count"],
            bucket_sign_agreement=derived["bucket_sign_agreement"],
            bucket_rank_agreement_all_ok_windows=derived["bucket_rank_agreement_all_ok_windows"],
        )
        assert result.outcome == EXPECTED_ASSET_OUTCOMES[symbol], symbol
        computed.append(result)

    overall = disposition.overall_disposition(computed)
    assert overall == disposition.OUTCOME_REJECTED


def test_methodology_markers_unchanged():
    assert disposition.METHODOLOGY_CLASSIFICATION == "FUTURE_AWARE_RESEARCH"
    assert disposition.METHODOLOGY_FUTURE_AWARE is True
    assert disposition.is_promotion_eligible(disposition_outcome=disposition.OUTCOME_REJECTED) is False
    assert disposition.is_promotion_eligible(disposition_outcome=disposition.OUTCOME_VALIDATED) is False
