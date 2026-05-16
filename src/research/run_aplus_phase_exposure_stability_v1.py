from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPORT_NAME = "aplus_phase_exposure_stability_v1"
PARSER_VERSION = "0.1"
SAMPLE_LIMITATION = "LOW_SAMPLE_THREE_SNAPSHOTS"

_STABILITY_CLASSES = [
    "FULLY_STABLE",
    "TABLE1_STABLE_TABLE2_DRIFT",
    "TABLE1_DRIFT_TABLE2_STABLE",
    "DRIFTING",
    "INSUFFICIENT_SNAPSHOTS",
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Measure A+ label phase/exposure stability across normalized paired "
            "snapshots (research-only, no DB, no broker)."
        )
    )
    p.add_argument(
        "--joined-paths",
        nargs="+",
        default=[
            "data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260514_1315_1256.jsonl",
            "data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260515_1244.jsonl",
            "data/research/aplus_table1_table2_normalized_v1/table1_table2_joined_20260516_0115_0117.jsonl",
        ],
        help="One or more paths to joined Table 1/Table 2 JSONL files.",
    )
    p.add_argument("--output-dir", default="data/research/aplus_phase_exposure_stability_v1")
    p.add_argument("--output", choices=["table", "json"], default="table")
    p.add_argument("--write-files", action="store_true")
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def pair_id_from_path(path: Path) -> str:
    stem = path.stem
    prefix = "table1_table2_joined_"
    return stem[len(prefix):] if stem.startswith(prefix) else stem


def parse_ts(text: str) -> datetime:
    return datetime.strptime(text.rstrip("Z"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def load_joined(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Derived exposure keys
# ---------------------------------------------------------------------------

_COMBINED_FIELDS = [
    "table1_phase",
    "table1_strategic_bias",
    "table2_harmonic_phase",
    "table2_offset_band",
    "table2_quality",
    "table2_extension_risk",
]


def combined_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(f) or "") for f in _COMBINED_FIELDS)


def get_str(row: dict[str, Any], key: str) -> str:
    return str(row.get(key) or "")


# ---------------------------------------------------------------------------
# Stability helpers
# ---------------------------------------------------------------------------

def is_stable(seq: list[str]) -> bool:
    return len(set(seq)) <= 1


def change_count(seq: list[str]) -> int:
    return sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1])


def classify_stability(
    n: int,
    t1_phase_ok: bool,
    t1_bias_ok: bool,
    t2_harmonic_ok: bool,
    t2_offset_ok: bool,
    t2_quality_ok: bool,
    t2_ext_risk_ok: bool,
) -> str:
    if n < 2:
        return "INSUFFICIENT_SNAPSHOTS"
    t1_stable = t1_phase_ok and t1_bias_ok
    t2_stable = t2_harmonic_ok and t2_offset_ok and t2_quality_ok and t2_ext_risk_ok
    if t1_stable and t2_stable:
        return "FULLY_STABLE"
    if t1_stable:
        return "TABLE1_STABLE_TABLE2_DRIFT"
    if t2_stable:
        return "TABLE1_DRIFT_TABLE2_STABLE"
    return "DRIFTING"


# ---------------------------------------------------------------------------
# Core: trajectories
# ---------------------------------------------------------------------------

def build_trajectories(
    token_data: dict[str, dict[str, dict[str, Any]]],
    snapshot_order: list[tuple[str, datetime]],
    all_pair_ids: list[str],
) -> list[dict[str, Any]]:
    pid_to_ts = {pid: ts for pid, ts in snapshot_order}
    out: list[dict[str, Any]] = []

    for token in sorted(token_data):
        present = [(pid, pid_to_ts[pid]) for pid, _ in snapshot_order if pid in token_data[token]]
        missing = [pid for pid in all_pair_ids if pid not in token_data[token]]
        if not present:
            continue

        first_ts = present[0][1].isoformat().replace("+00:00", "Z")
        last_ts = present[-1][1].isoformat().replace("+00:00", "Z")

        def seq(field: str) -> list[str]:
            return [get_str(token_data[token][pid], field) for pid, _ in present]

        t1p_seq = seq("table1_phase")
        t1b_seq = seq("table1_strategic_bias")
        t2h_seq = seq("table2_harmonic_phase")
        t2o_seq = seq("table2_offset_band")
        t2q_seq = seq("table2_quality")
        t2r_seq = seq("table2_extension_risk")
        c_seq = [combined_key(token_data[token][pid]) for pid, _ in present]

        t1p_stable = is_stable(t1p_seq)
        t1b_stable = is_stable(t1b_seq)
        t2h_stable = is_stable(t2h_seq)
        t2o_stable = is_stable(t2o_seq)
        t2q_stable = is_stable(t2q_seq)
        t2r_stable = is_stable(t2r_seq)
        c_stable = is_stable(c_seq)

        out.append({
            "token": token,
            "snapshot_count": len(present),
            "first_pair_reference_ts_utc": first_ts,
            "last_pair_reference_ts_utc": last_ts,
            "snapshots_present": [pid for pid, _ in present],
            "missing_snapshots": missing,
            "table1_phase_sequence": t1p_seq,
            "table1_strategic_bias_sequence": t1b_seq,
            "table2_harmonic_phase_sequence": t2h_seq,
            "table2_offset_band_sequence": t2o_seq,
            "table2_quality_sequence": t2q_seq,
            "table2_extension_risk_sequence": t2r_seq,
            "combined_exposure_sequence": c_seq,
            "table1_phase_stable": t1p_stable,
            "table1_bias_stable": t1b_stable,
            "table2_harmonic_phase_stable": t2h_stable,
            "table2_offset_band_stable": t2o_stable,
            "table2_quality_stable": t2q_stable,
            "table2_extension_risk_stable": t2r_stable,
            "combined_exposure_stable": c_stable,
            "table1_phase_change_count": change_count(t1p_seq),
            "table2_offset_band_change_count": change_count(t2o_seq),
            "combined_exposure_change_count": change_count(c_seq),
            "stability_class": classify_stability(
                len(present),
                t1p_stable, t1b_stable,
                t2h_stable, t2o_stable, t2q_stable, t2r_stable,
            ),
        })

    return out


# ---------------------------------------------------------------------------
# Core: transitions
# ---------------------------------------------------------------------------

def build_transitions(
    token_data: dict[str, dict[str, dict[str, Any]]],
    snapshot_order: list[tuple[str, datetime]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for i in range(len(snapshot_order) - 1):
        from_pid, from_ts = snapshot_order[i]
        to_pid, to_ts = snapshot_order[i + 1]
        hours = round((to_ts - from_ts).total_seconds() / 3600.0, 2)

        tokens_in_both = sorted(
            t for t in token_data
            if from_pid in token_data[t] and to_pid in token_data[t]
        )
        for token in tokens_in_both:
            fr = token_data[token][from_pid]
            to = token_data[token][to_pid]

            from_t1p = get_str(fr, "table1_phase");     to_t1p = get_str(to, "table1_phase")
            from_t1b = get_str(fr, "table1_strategic_bias"); to_t1b = get_str(to, "table1_strategic_bias")
            from_t2h = get_str(fr, "table2_harmonic_phase"); to_t2h = get_str(to, "table2_harmonic_phase")
            from_t2o = get_str(fr, "table2_offset_band"); to_t2o = get_str(to, "table2_offset_band")
            from_t2q = get_str(fr, "table2_quality");   to_t2q = get_str(to, "table2_quality")
            from_t2r = get_str(fr, "table2_extension_risk"); to_t2r = get_str(to, "table2_extension_risk")
            from_c = combined_key(fr);                  to_c = combined_key(to)

            out.append({
                "token": token,
                "from_snapshot_pair_id": from_pid,
                "to_snapshot_pair_id": to_pid,
                "from_pair_reference_ts_utc": from_ts.isoformat().replace("+00:00", "Z"),
                "to_pair_reference_ts_utc": to_ts.isoformat().replace("+00:00", "Z"),
                "hours_between_snapshots": hours,
                "from_table1_phase": from_t1p,
                "to_table1_phase": to_t1p,
                "table1_phase_changed": from_t1p != to_t1p,
                "from_table1_strategic_bias": from_t1b,
                "to_table1_strategic_bias": to_t1b,
                "table1_bias_changed": from_t1b != to_t1b,
                "from_table2_harmonic_phase": from_t2h,
                "to_table2_harmonic_phase": to_t2h,
                "table2_harmonic_phase_changed": from_t2h != to_t2h,
                "from_table2_offset_band": from_t2o,
                "to_table2_offset_band": to_t2o,
                "table2_offset_band_changed": from_t2o != to_t2o,
                "from_table2_quality": from_t2q,
                "to_table2_quality": to_t2q,
                "table2_quality_changed": from_t2q != to_t2q,
                "from_table2_extension_risk": from_t2r,
                "to_table2_extension_risk": to_t2r,
                "table2_extension_risk_changed": from_t2r != to_t2r,
                "from_combined_exposure_key": from_c,
                "to_combined_exposure_key": to_c,
                "combined_exposure_changed": from_c != to_c,
                "transition_signature": f"{from_pid}->{to_pid}:{from_c}->{to_c}",
            })

    return out


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def top_transitions(
    rows: list[dict[str, Any]],
    from_key: str,
    to_key: str,
    top_n: int = 5,
) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str]] = Counter()
    for row in rows:
        f = str(row.get(from_key) or "")
        t = str(row.get(to_key) or "")
        if f != t:
            counter[(f, t)] += 1
    return [{"from": k[0], "to": k[1], "count": v} for k, v in counter.most_common(top_n)]


def stability_rate(trajectories: list[dict[str, Any]], field: str) -> float | None:
    eligible = [r for r in trajectories if r["snapshot_count"] >= 2]
    if not eligible:
        return None
    stable = sum(1 for r in eligible if r[field])
    return round(100.0 * stable / len(eligible), 2)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary(
    trajectories: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    snapshot_pair_ids: list[str],
    input_rows: int,
    args: argparse.Namespace,
    output_paths: dict[str, str],
) -> dict[str, Any]:
    sc_raw = Counter(r["stability_class"] for r in trajectories)
    sc_counts = {k: sc_raw.get(k, 0) for k in _STABILITY_CLASSES}

    return {
        "report": REPORT_NAME,
        "parser_version": PARSER_VERSION,
        "scope": "research-only market-only account-agnostic",
        "limitation": SAMPLE_LIMITATION,
        "runtime_promotion_allowed": False,
        "feature_candidate_promotion_allowed": False,
        "input_snapshots": len(snapshot_pair_ids),
        "snapshot_pair_ids": snapshot_pair_ids,
        "input_rows": input_rows,
        "unique_tokens": len(trajectories),
        "transition_rows": len(transitions),
        "tokens_with_all_snapshots": sorted(r["token"] for r in trajectories if not r["missing_snapshots"]),
        "tokens_missing_any_snapshot": sorted(r["token"] for r in trajectories if r["missing_snapshots"]),
        "stability_class_counts": sc_counts,
        "table1_phase_stability_rate": stability_rate(trajectories, "table1_phase_stable"),
        "table1_bias_stability_rate": stability_rate(trajectories, "table1_bias_stable"),
        "table2_harmonic_phase_stability_rate": stability_rate(trajectories, "table2_harmonic_phase_stable"),
        "table2_offset_band_stability_rate": stability_rate(trajectories, "table2_offset_band_stable"),
        "table2_quality_stability_rate": stability_rate(trajectories, "table2_quality_stable"),
        "table2_extension_risk_stability_rate": stability_rate(trajectories, "table2_extension_risk_stable"),
        "combined_exposure_stability_rate": stability_rate(trajectories, "combined_exposure_stable"),
        "most_common_table1_phase_transitions": top_transitions(
            transitions, "from_table1_phase", "to_table1_phase"
        ),
        "most_common_table2_harmonic_phase_transitions": top_transitions(
            transitions, "from_table2_harmonic_phase", "to_table2_harmonic_phase"
        ),
        "most_common_table2_offset_band_transitions": top_transitions(
            transitions, "from_table2_offset_band", "to_table2_offset_band"
        ),
        "most_common_combined_exposure_transitions": top_transitions(
            transitions, "from_combined_exposure_key", "to_combined_exposure_key"
        ),
        "tokens_with_stable_offset_band": sorted(
            r["token"] for r in trajectories if r["table2_offset_band_stable"]
        ),
        "tokens_with_offset_band_drift": sorted(
            r["token"] for r in trajectories if not r["table2_offset_band_stable"]
        ),
        "tokens_with_stable_combined_exposure": sorted(
            r["token"] for r in trajectories if r["combined_exposure_stable"]
        ),
        "tokens_with_combined_exposure_drift": sorted(
            r["token"] for r in trajectories if not r["combined_exposure_stable"]
        ),
        "output_paths": output_paths,
        "wrote_files": bool(args.write_files),
        "safety_markers": {
            "broker_calls": 0,
            "broker_writes": 0,
            "order_submission": 0,
            "live_orders": 0,
            "db_writes": 0,
            "selection_engine_changes": 0,
            "advice_engine_changes": 0,
            "decision_gate_changes": 0,
            "execution_planner_changes": 0,
            "executor_changes": 0,
            "paper_live_logic": "not_allowed",
            "account_state": "not_allowed",
            "research_only": True,
            "market_only": True,
            "account_agnostic": True,
        },
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _pct(v: float | None) -> str:
    return f"{v:.1f}%" if v is not None else "—"


def render_table(summary: dict[str, Any]) -> str:
    lines: list[str] = [
        f"report={REPORT_NAME} version={PARSER_VERSION}",
        "scope=research-only market-only account-agnostic",
        "db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0",
        "selection_engine=none advice_engine=none decision_gate=none execution_planner=none executor=none",
        f"limitation={SAMPLE_LIMITATION}  runtime_promotion_allowed=False  feature_candidate_promotion_allowed=False",
        (
            f"input_snapshots={summary['input_snapshots']}  "
            f"unique_tokens={summary['unique_tokens']}  "
            f"transition_rows={summary['transition_rows']}"
        ),
        "",
        "--- stability class counts ---",
    ]
    for sc in _STABILITY_CLASSES:
        lines.append(f"  {sc}={summary['stability_class_counts'].get(sc, 0)}")

    lines += [
        "",
        "--- stability rates (tokens with >= 2 snapshots) ---",
        f"  table1_phase_stability_rate={_pct(summary['table1_phase_stability_rate'])}",
        f"  table1_bias_stability_rate={_pct(summary['table1_bias_stability_rate'])}",
        f"  table2_harmonic_phase_stability_rate={_pct(summary['table2_harmonic_phase_stability_rate'])}",
        f"  table2_offset_band_stability_rate={_pct(summary['table2_offset_band_stability_rate'])}",
        f"  table2_quality_stability_rate={_pct(summary['table2_quality_stability_rate'])}",
        f"  table2_extension_risk_stability_rate={_pct(summary['table2_extension_risk_stability_rate'])}",
        f"  combined_exposure_stability_rate={_pct(summary['combined_exposure_stability_rate'])}",
        "",
        "--- top table2_offset_band transitions ---",
    ]
    for t in summary["most_common_table2_offset_band_transitions"]:
        lines.append(f"  {t['from']} -> {t['to']}  count={t['count']}")
    if not summary["most_common_table2_offset_band_transitions"]:
        lines.append("  (none)")

    lines += ["", "--- top table1_phase transitions ---"]
    for t in summary["most_common_table1_phase_transitions"]:
        lines.append(f"  {t['from']} -> {t['to']}  count={t['count']}")
    if not summary["most_common_table1_phase_transitions"]:
        lines.append("  (none)")

    lines += ["", "--- top combined_exposure transitions (up to 3) ---"]
    for t in summary["most_common_combined_exposure_transitions"][:3]:
        lines.append(f"  [{t['count']}x]  {t['from']}")
        lines.append(f"        -> {t['to']}")
    if not summary["most_common_combined_exposure_transitions"]:
        lines.append("  (none)")

    stable_off = summary["tokens_with_stable_offset_band"]
    drift_off = summary["tokens_with_offset_band_drift"]
    stable_comb = summary["tokens_with_stable_combined_exposure"]
    drift_comb = summary["tokens_with_combined_exposure_drift"]

    lines += [
        "",
        f"tokens_with_stable_offset_band ({len(stable_off)}): {','.join(stable_off)}",
        f"tokens_with_offset_band_drift ({len(drift_off)}): {','.join(drift_off) or 'none'}",
        f"tokens_with_stable_combined_exposure ({len(stable_comb)}): {','.join(stable_comb) or 'none'}",
        f"tokens_with_combined_exposure_drift ({len(drift_comb)}): {','.join(drift_comb)}",
        "",
        f"wrote_files={summary['wrote_files']}",
    ]
    if summary["wrote_files"]:
        for k, v in summary["output_paths"].items():
            lines.append(f"  {k}={v}")
    lines.append("[DONE] db_writes=0 broker_calls=0 broker_writes=0 order_submission=0 live_orders=0")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    joined_paths = [Path(p) for p in args.joined_paths]
    out_dir = Path(args.output_dir)

    output_paths = {
        "trajectories_jsonl": str(out_dir / "token_phase_exposure_trajectories_v1.jsonl"),
        "transitions_jsonl": str(out_dir / "phase_exposure_transition_rows_v1.jsonl"),
        "summary_json": str(out_dir / "phase_exposure_stability_summary_v1.json"),
    }

    # Load and sort snapshots by pair_reference_ts_utc.
    raw_snapshots: list[tuple[str, datetime, list[dict[str, Any]]]] = []
    for path in joined_paths:
        if not path.exists():
            print(f"ERROR: not found: {path}")
            return 2
        pair_id = pair_id_from_path(path)
        rows = load_joined(path)
        if not rows:
            print(f"ERROR: empty: {path}")
            return 2
        pair_ref_ts = parse_ts(str(rows[0]["pair_reference_ts_utc"]))
        raw_snapshots.append((pair_id, pair_ref_ts, rows))

    raw_snapshots.sort(key=lambda x: x[1])
    snapshot_order: list[tuple[str, datetime]] = [(pid, ts) for pid, ts, _ in raw_snapshots]
    all_pair_ids = [pid for pid, _ in snapshot_order]

    # Build per-token per-snapshot lookup.
    token_data: dict[str, dict[str, dict[str, Any]]] = {}
    input_rows = 0
    for pair_id, _, rows in raw_snapshots:
        input_rows += len(rows)
        for row in rows:
            token = str(row["token"]).upper()
            token_data.setdefault(token, {})[pair_id] = row

    trajectories = build_trajectories(token_data, snapshot_order, all_pair_ids)
    transitions = build_transitions(token_data, snapshot_order)
    summary = build_summary(trajectories, transitions, all_pair_ids, input_rows, args, output_paths)

    if args.write_files:
        write_jsonl(Path(output_paths["trajectories_jsonl"]), trajectories)
        write_jsonl(Path(output_paths["transitions_jsonl"]), transitions)
        write_json(Path(output_paths["summary_json"]), summary)

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(render_table(summary))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
