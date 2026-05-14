from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


REPORT_NAME = "strategy_regime_property_inventory_v1"
REPORT_VERSION = "0.1"

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "venv",
    ".venv",
    "logs",
    "data",
}

SCAN_ROOTS = (
    "src",
    "docs/core",
    "docs/research",
)

DISCOVERY_PATTERNS = (
    ("btc_context", re.compile(r"\bbtc_prior_24h\b|\bBTC\b.*\b24h\b", re.I)),
    ("rotation_context", re.compile(r"\brotation_bucket\b|\bROTATION_", re.I)),
    ("classification", re.compile(r"\bclassification_code\b|\bPULLBACK_WATCH\b|\bRECLAIM\b|\bCOMPRESSION\b|\bSPIKE\b", re.I)),
    ("selection_state", re.compile(r"\bselection_state\b|\bWATCHLIST\b|\bBUY_READY\b|\bPREPARE\b|\bAVOID\b", re.I)),
    ("rank_score", re.compile(r"\bpriority_rank\b|\bselection_score\b|\brank\b.*\bsweet", re.I)),
    ("quality", re.compile(r"\bquality_status\b|\bTRUSTED\b|\bDEGRADED\b|\bBLOCKED\b", re.I)),
    ("zone_context", re.compile(r"\bentry_zone\b|\btp_zone\b|\binvalidation_price\b|\bleg_direction\b", re.I)),
    ("aplus_context", re.compile(r"\bAPLUS_\b|\baplus_bucket\b|\bcanonical\b|\bbreathline\b", re.I)),
    ("breath_curve", re.compile(r"\bbreath_curve\b|\boffset_match\b|\bphase_offset\b|\b0\.618\b|\b0\.786\b|\b1\.272\b", re.I)),
    ("policy_decision", re.compile(r"\bpolicy_decision\b|\ballowed_now\b|\bBLOCK_FOR_24H\b|\bINSUFFICIENT_SAMPLE\b", re.I)),
    ("execution_boundary", re.compile(r"\bdecision_gate\b|\bexecution_planner\b|\bexecutor\b|\bbroker_writes=0\b|\border_submission=0\b", re.I)),
)

FILE_HINT_RE = re.compile(
    r"(strategy|policy|backtest|regime|selection|advice|trade_setup|breath|paper_candidate|dashboard|zone)",
    re.I,
)


@dataclass(frozen=True)
class InventoryItem:
    artifact: str
    layer: str
    source_paths: list[str]
    current_role: str
    extracted_regime_properties: list[str]
    candidate_good_regime: list[str]
    candidate_bad_regime: list[str]
    validation_status: str
    missing_validation: list[str]
    architecture_boundary: str
    next_action: str


@dataclass(frozen=True)
class DiscoveredFile:
    path: str
    hits: dict[str, int]


def run_git(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return "UNKNOWN"

    if result.returncode != 0:
        return "UNKNOWN"

    return result.stdout.strip() or "UNKNOWN"


def existing_paths(paths: Iterable[str]) -> list[str]:
    result = []
    for value in paths:
        if Path(value).exists():
            result.append(value)
    return result


def curated_inventory() -> list[InventoryItem]:
    return [
        InventoryItem(
            artifact="selection_engine_v2",
            layer="selection_engine",
            source_paths=existing_paths([
                "src/selection/selection_engine_v2.py",
                "src/selection/run_selection_engine_v2.py",
                "configs/selection_engine_v2.yaml",
            ]),
            current_role="Market-only ranking and candidate selection. Account-agnostic. Produces selection_state, selection_bias, score, rank, quality and allowed sleeve context.",
            extracted_regime_properties=[
                "selection_state",
                "selection_bias",
                "selection_score",
                "priority_rank",
                "quality_status_1d",
                "quality_status_4h",
                "quality_status_1h",
                "timing_refinement_score",
                "regime_label_4h if present",
                "allowed_sleeves as market suitability context, not account permission",
            ],
            candidate_good_regime=[
                "ranked early rotation candidate",
                "trusted multi-timeframe quality",
                "constructive pullback/reclaim context",
                "defensive but improving setup",
            ],
            candidate_bad_regime=[
                "quality degraded or blocked",
                "rank decay",
                "neutral/avoid state despite narrative strength",
                "conflicting higher-timeframe structure",
            ],
            validation_status="Partial. Selection output exists and can be joined to forward returns, but regime extraction is not yet formalized.",
            missing_validation=[
                "Forward return by selection_state x class x BTC context",
                "Rank decay and false-positive analysis",
                "Quality penalty contribution by regime",
            ],
            architecture_boundary="May inform regime selector and policy router after validation. Must not become account-aware and must not place orders.",
            next_action="Use as primary source for market-only strategy fingerprints.",
        ),
        InventoryItem(
            artifact="trade_setup_filter_v1",
            layer="research_policy_filter",
            source_paths=existing_paths([
                "src/trade_setup_filter/run_trade_setup_filter_v1.py",
                "docs/core/trade_setup_filter_v1.md",
            ]),
            current_role="Filters current selection candidates using rank, market context and setup suitability before policy preview.",
            extracted_regime_properties=[
                "btc_prior_24h",
                "selection_state",
                "priority_rank",
                "selection_score",
                "setup_filter_state",
                "setup_filter_reason",
                "target_horizon as observed outcome hint, not regime definition",
            ],
            candidate_good_regime=[
                "early rotation pullback/reclaim setup",
                "BTC weak-but-not-breaking context",
                "WATCHLIST rank sweet spot",
                "candidate weak set where pullback mean reversion can work",
            ],
            candidate_bad_regime=[
                "rank outside sweet spot",
                "selection_state not eligible",
                "BTC breakdown",
                "late chase after move",
            ],
            validation_status="Medium. It already produces observations. Needs full regime/class slicing.",
            missing_validation=[
                "Backtest pass/fail by BTC prior return buckets",
                "Backtest pass/fail by asset class",
                "Forward return by setup_filter_reason",
                "MAE/MFE versus entry/TP/invalidation zones",
            ],
            architecture_boundary="Research/preview filter only. Should not encode live/paper mode. Should not own account permission.",
            next_action="Extract setup_filter_reason as strategy fingerprint input.",
        ),
        InventoryItem(
            artifact="trade_setup_filter_policy_preview_v1",
            layer="research_policy_preview",
            source_paths=existing_paths([
                "src/research/run_trade_setup_filter_policy_preview_v1.py",
                "docs/research/trade_setup_filter_policy_preview_v1.md",
            ]),
            current_role="Preview layer that blocks/allows current 24h policy candidates based on historical sample evidence.",
            extracted_regime_properties=[
                "policy_decision",
                "suggested_horizon",
                "allowed_now",
                "sample sufficiency",
                "current_target_horizon",
            ],
            candidate_good_regime=[
                "sufficient historical sample for current setup class",
                "current candidate belongs to validated historical bucket",
            ],
            candidate_bad_regime=[
                "BLOCK_FOR_24H",
                "INSUFFICIENT_SAMPLE",
                "policy sample mismatch",
            ],
            validation_status="Early but useful. It correctly behaves as evidence preview, not execution permission.",
            missing_validation=[
                "Replace horizon-as-manual-regime with regime selector output",
                "Backtest policy decisions by global regime and class regime",
                "Store sample size and confidence bands explicitly",
            ],
            architecture_boundary="Must remain research preview until promoted. Do not mix with decision_gate or executor.",
            next_action="Convert horizon-specific preview into regime-aware policy evidence.",
        ),
        InventoryItem(
            artifact="paper_advice_policy_v1",
            layer="paper_navigation",
            source_paths=existing_paths([
                "src/advice/paper_advice_policy_v1.py",
                "src/advice/run_paper_advice_policy_v1.py",
                "docs/core/paper_advice_policy_v1.md",
            ]),
            current_role="Read-only navigation aggregation. Combines selection, setup filter, policy preview, A+ bucket and execution zones into advice_state/action.",
            extracted_regime_properties=[
                "advice_state",
                "advice_action",
                "aplus_bucket",
                "setup_filter_state",
                "policy_decision",
                "leg_direction",
                "entry_zone",
                "tp_zone",
                "invalidation_price",
                "confidence_score",
                "risk_label",
            ],
            candidate_good_regime=[
                "WATCH_CORE with setup confirmation",
                "CORE_CONTEXT plus reclaim",
                "WATCH where caution is explicit and zones are valid",
            ],
            candidate_bad_regime=[
                "NO_NEW_BUY",
                "AVOID",
                "BLOCK_24H",
                "WAIT without setup confirmation",
            ],
            validation_status="Operational as static dashboard input. Not yet a validated strategy.",
            missing_validation=[
                "Advice_state forward return analysis",
                "Advice_action transition analysis over time",
                "Entry/TP/invalidation hit-rate validation",
                "Separation of regime property from dashboard presentation",
            ],
            architecture_boundary="Must stay market-only and account-agnostic. PAPER/LIVE mode is not a regime property. It belongs to runtime/deployment and later execution permission.",
            next_action="Use as dashboard-facing interpretation layer, not as source of execution truth.",
        ),
        InventoryItem(
            artifact="paper_advice_static_dashboard_v1",
            layer="reporting",
            source_paths=existing_paths([
                "src/reporting/run_paper_advice_static_dashboard_v1.py",
                "docs/core/paper_advice_static_dashboard_v1.md",
                "scripts/publish_paper_advice_dashboard_to_odroid.sh",
            ]),
            current_role="Static read-only dashboard publisher. Shows latest paper_advice_observation snapshot.",
            extracted_regime_properties=[
                "None. Reporting layer only.",
            ],
            candidate_good_regime=[
                "Not applicable",
            ],
            candidate_bad_regime=[
                "Not applicable",
            ],
            validation_status="Working deployment/reporting utility.",
            missing_validation=[
                "No strategy validation belongs here",
            ],
            architecture_boundary="No strategy logic, no regime selection, no execution. Dashboard is display only.",
            next_action="Keep as observer. Do not add strategy shortcuts here.",
        ),
        InventoryItem(
            artifact="breath_curve_research_policy_backtest_v1",
            layer="research_backtest",
            source_paths=existing_paths([
                "src/research/run_breath_curve_research_policy_backtest_v1.py",
                "docs/research/breath_curve_research_policy_backtest_v1.md",
            ]),
            current_role="Research execution simulation for Breath Curve checkpoints and outcomes.",
            extracted_regime_properties=[
                "anchor_ts",
                "checkpoint",
                "offset_match",
                "full alignment score",
                "0.618 recognition",
                "0.786 recognition",
                "1.000 pulse outcome",
                "1.272 extension outcome",
            ],
            candidate_good_regime=[
                "phase-locked symbol behaviour",
                "clean 0.618 or 0.786 recognition",
                "positive extension behaviour with stable offset",
            ],
            candidate_bad_regime=[
                "half-phase drift",
                "offset instability",
                "late overshoot without early recognition",
                "regime-shift flagged asset",
            ],
            validation_status="Research-only. Useful for phase/regime hypotheses, not selection modifiers yet.",
            missing_validation=[
                "Non-overlap validation by symbol",
                "Regime bucket comparison",
                "Random anchor baseline",
                "Class-specific phase stability",
            ],
            architecture_boundary="Must stay market-only research. No selection_engine modifier until validated.",
            next_action="Feed regime selector as optional phase-context candidate only after stronger validation.",
        ),
        InventoryItem(
            artifact="breath_curve_regime_gated_policy_preview_v1",
            layer="research_policy_preview",
            source_paths=existing_paths([
                "src/research/run_breath_curve_regime_gated_policy_preview_v1.py",
                "docs/research/breath_curve_regime_gated_policy_preview_v1.md",
            ]),
            current_role="Preview for gating Breath Curve policy by regime diagnostics.",
            extracted_regime_properties=[
                "regime gate pass/fail",
                "phase cohort",
                "symbol-specific alignment",
                "offset stability",
            ],
            candidate_good_regime=[
                "stable phase cohort",
                "offset match aligns with positive forward outcome",
            ],
            candidate_bad_regime=[
                "offset edge cases",
                "drift after checkpoint",
                "speculative/unstable phase behaviour",
            ],
            validation_status="Early research lane.",
            missing_validation=[
                "Compare against strategy-independent global regime",
                "Compare asset-class regime versus symbol-specific regime",
                "Quantify whether gate adds edge beyond selection_engine_v2",
            ],
            architecture_boundary="Research-only. No decision or execution side effects.",
            next_action="Use as one candidate feature family for regime selector backtest.",
        ),
        InventoryItem(
            artifact="A+ canonical Table 1 regime gate validation",
            layer="external_research_context",
            source_paths=existing_paths([
                "src/research/run_aplus_table1_regime_gate_validation_v1.py",
                "docs/research/aplus_table1_regime_gate_validation_v1.md",
                "data/aplus_raw/2026-05-13_1915_table1_canonical_breathline.txt",
            ]),
            current_role="External narrative/field context normalized into buckets such as APLUS_CANONICAL_CORE, APLUS_CAUTION and APLUS_AVOID.",
            extracted_regime_properties=[
                "phase",
                "coherence",
                "field",
                "geometry",
                "structural_role",
                "expansion_quality",
                "anchor_strength",
                "strategic_bias",
                "aplus_bucket",
            ],
            candidate_good_regime=[
                "canonical core with clean geometry and strong anchor",
                "anchor context with market setup confirmation",
            ],
            candidate_bad_regime=[
                "APLUS_AVOID",
                "low coherence",
                "distorted geometry",
                "exhaustion/collapse phase",
            ],
            validation_status="External research context. Needs market validation before any strategic weight.",
            missing_validation=[
                "Forward returns by aplus_bucket",
                "A+ bucket interaction with selection_state",
                "A+ bucket interaction with asset class",
                "Failure analysis for canonical core assets in AVOID market setups",
            ],
            architecture_boundary="External narrative may label context. It must not bypass validated market signals.",
            next_action="Treat as exogenous regime prior, not direct trade advice.",
        ),
        InventoryItem(
            artifact="swing_pullback_recovery_v5 / paper candidate preview",
            layer="research_backtest_staging",
            source_paths=existing_paths([
                "src/research/paper_candidate_contract_v1.py",
                "docs/research/paper_candidate_contract_v1.md",
            ]),
            current_role="Research staging contract for market-only paper candidates derived from historical backtest filters.",
            extracted_regime_properties=[
                "btc_prior_24h window",
                "rotation_bucket",
                "classification_code",
                "selection_state",
                "priority_rank",
                "sleeve_fit_code",
                "simulated_horizon_hours",
                "simulated_net_return",
            ],
            candidate_good_regime=[
                "ROTATION_EARLY",
                "PULLBACK_WATCH",
                "WATCHLIST rank 1-10",
                "BTC prior 24h weak but controlled",
            ],
            candidate_bad_regime=[
                "BTC breakdown",
                "late rotation",
                "rank outside accepted band",
                "negative simulated net return clusters",
            ],
            validation_status="Promising. This is likely one of the cleanest sources for regime signature extraction.",
            missing_validation=[
                "Rebuild replay by class and regime",
                "Evaluate 4h/24h/72h forward returns",
                "Check whether the edge is global, class-specific or symbol-specific",
            ],
            architecture_boundary="Contract is research-only and explicitly forbids account/order/execution fields.",
            next_action="Use as first seed strategy for regime selector backtest.",
        ),
        InventoryItem(
            artifact="execution_zone_context / zone_engine_v1",
            layer="measurement",
            source_paths=existing_paths([
                "src/zone/run_zone_engine_v1.py",
                "docs/core/execution_zone_context_v1.md",
            ]),
            current_role="Market measurement of entry/target/invalidation zones. Despite the name, it is context, not execution.",
            extracted_regime_properties=[
                "leg_direction",
                "entry_zone_low/high/type",
                "tp_zone_low/high/type",
                "invalidation_price",
                "zone_confidence_score",
                "zone_alignment_score",
            ],
            candidate_good_regime=[
                "valid zones with strong confidence",
                "entry zone near current market",
                "asymmetric TP/invalidation structure",
            ],
            candidate_bad_regime=[
                "inverted or stale zones",
                "low alignment",
                "target below entry for long context unless leg_direction is DOWN",
            ],
            validation_status="Operational measurement. Needs hit-rate validation.",
            missing_validation=[
                "Entry touch rate",
                "TP hit rate",
                "Invalidation hit rate",
                "MAE/MFE by selection/advice/regime",
            ],
            architecture_boundary="Measurement only. It must not decide entries by itself.",
            next_action="Join zone outcomes to strategy-regime backtest.",
        ),
        InventoryItem(
            artifact="decision_gate / execution_planner / executor",
            layer="excluded_from_regime_definition",
            source_paths=existing_paths([
                "src/decision_gate",
                "src/execution_planner",
                "src/executor",
                "src/execution",
            ]),
            current_role="Account-aware permission, execution intent and order handling layers.",
            extracted_regime_properties=[
                "None. These are not regime sources.",
            ],
            candidate_good_regime=[
                "Not applicable",
            ],
            candidate_bad_regime=[
                "Not applicable",
            ],
            validation_status="Explicit exclusion.",
            missing_validation=[
                "No regime validation belongs here",
            ],
            architecture_boundary="Do not use account_id, sleeve balances, live/paper mode, notional, broker permission or order state as regime inputs.",
            next_action="Keep clean separation. Regime selector must sit upstream as market-only context.",
        ),
    ]


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def scan_file(path: Path) -> DiscoveredFile | None:
    if should_skip(path):
        return None
    if not path.is_file():
        return None
    if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".sql", ".sh"}:
        return None
    if path.stat().st_size > 750_000:
        return None

    rel = str(path)
    name_hint = FILE_HINT_RE.search(rel) is not None

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    hits: dict[str, int] = {}
    for name, pattern in DISCOVERY_PATTERNS:
        found = pattern.findall(text)
        if found:
            hits[name] = len(found)

    if not hits and not name_hint:
        return None

    return DiscoveredFile(path=rel, hits=hits)


def discover_files(repo_root: Path, max_files: int) -> list[DiscoveredFile]:
    found: list[DiscoveredFile] = []
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            item = scan_file(path)
            if item is not None:
                found.append(item)

    def score(item: DiscoveredFile) -> tuple[int, str]:
        return (sum(item.hits.values()), item.path)

    return sorted(found, key=score, reverse=True)[:max_files]


def fmt_list(values: list[str]) -> str:
    if not values:
        return "- none"
    return "\n".join(f"- {value}" for value in values)


def render_markdown(items: list[InventoryItem], discovered: list[DiscoveredFile]) -> str:
    generated_ts = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    git_head = run_git(["log", "--oneline", "--decorate", "-1"])

    lines: list[str] = []
    lines.append("# Strategy Regime Property Inventory v1")
    lines.append("")
    lines.append(f"Generated: {generated_ts}")
    lines.append("")
    lines.append(f"Git HEAD: {git_head}")
    lines.append("")
    lines.append("## Status")
    lines.append("")
    lines.append("Research-only inventory. This document extracts candidate regime properties from existing Synth strategies, policies, research backtests and measurement layers.")
    lines.append("")
    lines.append("It does not create orders, execution intent, account permission, live/paper routing, or broker calls.")
    lines.append("")
    lines.append("## Core design decision")
    lines.append("")
    lines.append("Regime should be inferred from historically validated strategy behaviour, not manually selected by horizon.")
    lines.append("")
    lines.append("Correct flow:")
    lines.append("")
    lines.append("    existing strategies and backtests")
    lines.append("      -> extract implicit market conditions")
    lines.append("      -> validate forward outcomes by condition")
    lines.append("      -> define regime signatures")
    lines.append("      -> regime selector")
    lines.append("      -> policy router")
    lines.append("")
    lines.append("Incorrect flow:")
    lines.append("")
    lines.append("    horizon = regime")
    lines.append("    paper/live = regime")
    lines.append("    account permission = regime")
    lines.append("")
    lines.append("## Non-regime fields")
    lines.append("")
    lines.append("The following must not become regime inputs:")
    lines.append("")
    lines.append("- execution_mode")
    lines.append("- PAPER versus LIVE")
    lines.append("- account_id")
    lines.append("- sleeve balances or available equity")
    lines.append("- max notional")
    lines.append("- broker write permission")
    lines.append("- order state")
    lines.append("- executor state")
    lines.append("")
    lines.append("These belong to runtime, decision_gate, execution_planner or executor. Regime selector must remain market-only and account-agnostic.")
    lines.append("")
    lines.append("## Inventory")
    lines.append("")

    for item in items:
        lines.append(f"### {item.artifact}")
        lines.append("")
        lines.append(f"- Layer: {item.layer}")
        lines.append(f"- Current role: {item.current_role}")
        lines.append("- Source paths:")
        lines.append(fmt_list(item.source_paths or ["not found in current checkout"]))
        lines.append("")
        lines.append("Candidate regime properties:")
        lines.append("")
        lines.append(fmt_list(item.extracted_regime_properties))
        lines.append("")
        lines.append("Candidate good regime:")
        lines.append("")
        lines.append(fmt_list(item.candidate_good_regime))
        lines.append("")
        lines.append("Candidate bad regime:")
        lines.append("")
        lines.append(fmt_list(item.candidate_bad_regime))
        lines.append("")
        lines.append(f"Validation status: {item.validation_status}")
        lines.append("")
        lines.append("Missing validation:")
        lines.append("")
        lines.append(fmt_list(item.missing_validation))
        lines.append("")
        lines.append(f"Architecture boundary: {item.architecture_boundary}")
        lines.append("")
        lines.append(f"Next action: {item.next_action}")
        lines.append("")

    lines.append("## Discovered regime-relevant files")
    lines.append("")
    lines.append("| File | Pattern hits |")
    lines.append("|---|---:|")
    for file in discovered:
        hit_text = ", ".join(f"{key}={value}" for key, value in sorted(file.hits.items()))
        if not hit_text:
            hit_text = "filename hint only"
        lines.append(f"| `{file.path}` | {hit_text} |")

    lines.append("")
    lines.append("## Proposed next backtest")
    lines.append("")
    lines.append("Name: regime_selector_backtest_v1")
    lines.append("")
    lines.append("Compare these selector designs:")
    lines.append("")
    lines.append("- Global regime only")
    lines.append("- Asset-class regime only")
    lines.append("- Symbol-specific regime only")
    lines.append("- Global regime x asset class")
    lines.append("- Strategy-specific regime signature")
    lines.append("")
    lines.append("Outcome metrics:")
    lines.append("")
    lines.append("- forward return over 4h, 24h, 72h")
    lines.append("- max adverse excursion")
    lines.append("- max favourable excursion")
    lines.append("- entry zone touch rate")
    lines.append("- TP zone hit rate")
    lines.append("- invalidation hit rate")
    lines.append("- rank decay")
    lines.append("- state transition quality")
    lines.append("")
    lines.append("## Architecture target")
    lines.append("")
    lines.append("    market observations/features")
    lines.append("      -> regime_selector")
    lines.append("      -> active_regime_observation")
    lines.append("      -> policy_router")
    lines.append("      -> active_strategy_profile")
    lines.append("      -> selection/advice modifiers after validation")
    lines.append("")
    lines.append("No decision_gate, execution_planner or executor changes are implied by this inventory.")
    lines.append("")

    return "\n".join(lines)


def print_table(items: list[InventoryItem], discovered: list[DiscoveredFile], output_doc: Path) -> None:
    print(f"report={REPORT_NAME} version={REPORT_VERSION}")
    print("scope=research-only market-only account-agnostic")
    print("broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    print(f"inventory_items={len(items)}")
    print(f"discovered_files={len(discovered)}")
    print(f"output_doc={output_doc}")
    print()
    print("--- inventory artifacts ---")
    for item in items:
        print(f"{item.layer} | {item.artifact}")
    print()
    print("--- top discovered files ---")
    for item in discovered[:20]:
        hit_text = ", ".join(f"{key}={value}" for key, value in sorted(item.hits.items())) or "filename hint only"
        print(f"{item.path} | {hit_text}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build strategy regime property inventory v1.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-doc", default="docs/research/strategy_regime_property_inventory_v1.md")
    parser.add_argument("--max-discovered", type=int, default=80)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output_doc = Path(args.output_doc)

    items = curated_inventory()
    discovered = discover_files(repo_root, args.max_discovered)

    output_doc.parent.mkdir(parents=True, exist_ok=True)
    output_doc.write_text(render_markdown(items, discovered), encoding="utf-8")

    if args.output == "json":
        print(json.dumps({
            "report": REPORT_NAME,
            "version": REPORT_VERSION,
            "scope": "research-only market-only account-agnostic",
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "output_doc": str(output_doc),
            "inventory": [asdict(item) for item in items],
            "discovered": [asdict(item) for item in discovered],
        }, indent=2))
    else:
        print_table(items, discovered, output_doc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
