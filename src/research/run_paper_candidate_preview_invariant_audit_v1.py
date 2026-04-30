from __future__ import annotations

# Synth v2 - Paper Candidate Preview Invariant Audit V1.
#
# LAYER:
# research / paper-candidate preview audit
#
# BOUNDARY:
# Allowed:
# - read JSON output from read-only paper preview tools
# - compare PnL, exposure, and ledger preview summaries
# - fail loudly on simulation consistency mismatches
#
# Forbidden:
# - database writes
# - decision_state writes
# - execution_plan writes
# - live orders
# - account balance mutation
#
# NOTE:
# This audit intentionally validates research and backtest preview outputs only.

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_DIR = "/tmp/synth_paper_candidate_audit"
DEFAULT_PNL_JSON = DEFAULT_AUDIT_DIR + "/pnl_preview.json"
DEFAULT_EXPOSURE_JSON = DEFAULT_AUDIT_DIR + "/exposure_preview.json"
DEFAULT_LEDGER_JSON = DEFAULT_AUDIT_DIR + "/ledger_preview.json"


@dataclass(frozen=True)
class AuditCheck:
    name: str
    passed: bool
    left: str | None = None
    right: str | None = None
    note: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit read-only paper candidate preview JSON outputs for internal consistency."
    )
    parser.add_argument("--pnl-json", default=DEFAULT_PNL_JSON)
    parser.add_argument("--exposure-json", default=DEFAULT_EXPOSURE_JSON)
    parser.add_argument("--ledger-json", default=DEFAULT_LEDGER_JSON)
    parser.add_argument("--output", choices=("table", "json"), default="table")
    return parser.parse_args()


def load_json(path_value: str) -> Any:
    path = Path(path_value)
    if not path.exists():
        raise FileNotFoundError(f"JSON file does not exist: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"JSON file is empty: {path}")
    return json.loads(text)


def find_dict_with_key(obj: Any, key: str) -> dict[str, Any] | None:
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for value in obj.values():
            found = find_dict_with_key(value, key)
            if found is not None:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = find_dict_with_key(value, key)
            if found is not None:
                return found
    return None


def dec(value: Any) -> Decimal:
    return Decimal(str(value))


def string_value(value: Any) -> str:
    return str(value)


def check_equal(name: str, left: Any, right: Any) -> AuditCheck:
    return AuditCheck(
        name=name,
        passed=left == right,
        left=string_value(left),
        right=string_value(right),
    )


def check_decimal_equal(name: str, left: Any, right: Any) -> AuditCheck:
    left_dec = dec(left)
    right_dec = dec(right)
    return AuditCheck(
        name=name,
        passed=left_dec == right_dec,
        left=string_value(left_dec),
        right=string_value(right_dec),
    )


def require_summary(payload: Any, key: str, label: str) -> dict[str, Any]:
    summary = find_dict_with_key(payload, key)
    if summary is None:
        raise ValueError(f"{label} summary not found. Missing key: {key}")
    return summary


def build_checks(
    *,
    pnl_summary: dict[str, Any],
    exposure_summary: dict[str, Any],
    ledger_summary: dict[str, Any],
) -> list[AuditCheck]:
    checks: list[AuditCheck] = []

    checks.append(check_equal("trades_match_pnl_ledger", int(pnl_summary["trades"]), int(ledger_summary["trades"])))
    checks.append(check_equal("symbols_match_pnl_ledger", int(pnl_summary["symbols"]), int(ledger_summary["symbols"])))
    checks.append(check_equal("wins_match_pnl_ledger", int(pnl_summary["wins"]), int(ledger_summary["wins"])))
    checks.append(check_equal("losses_match_pnl_ledger", int(pnl_summary["losses"]), int(ledger_summary["losses"])))
    checks.append(check_decimal_equal("pnl_total_match", pnl_summary["total_sim_pnl_eur"], ledger_summary["total_sim_pnl_eur"]))
    checks.append(check_decimal_equal("gross_notional_match", pnl_summary["gross_notional_eur"], ledger_summary["gross_notional_eur"]))
    checks.append(check_decimal_equal("avg_sim_return_match", pnl_summary["avg_sim_return"], ledger_summary["avg_sim_return"]))
    checks.append(check_equal("ledger_return_mismatch_zero", int(ledger_summary["return_mismatch_rows"]), 0))

    checks.append(check_equal("exposure_capacity_pass", string_value(exposure_summary["capacity_state"]), "PASS"))
    checks.append(check_equal("trades_match_pnl_exposure", int(pnl_summary["trades"]), int(exposure_summary["trades"])))
    checks.append(check_equal("symbols_match_pnl_exposure", int(pnl_summary["symbols"]), int(exposure_summary["symbols"])))
    checks.append(check_decimal_equal("pnl_total_match_exposure", pnl_summary["total_sim_pnl_eur"], exposure_summary["total_sim_pnl_eur"]))
    checks.append(check_decimal_equal("gross_turnover_match_exposure", pnl_summary["gross_notional_eur"], exposure_summary["gross_turnover_notional_eur"]))

    return checks


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    pnl = load_json(args.pnl_json)
    exposure = load_json(args.exposure_json)
    ledger = load_json(args.ledger_json)

    pnl_summary = require_summary(pnl, "total_sim_pnl_eur", "pnl")
    exposure_summary = require_summary(exposure, "capacity_state", "exposure")
    ledger_summary = require_summary(ledger, "return_mismatch_rows", "ledger")

    checks = build_checks(
        pnl_summary=pnl_summary,
        exposure_summary=exposure_summary,
        ledger_summary=ledger_summary,
    )
    failed = [check for check in checks if not check.passed]

    return {
        "audit_version": "paper_candidate_preview_invariant_audit_v1",
        "status": "PASS" if not failed else "FAIL",
        "inputs": {
            "pnl_json": args.pnl_json,
            "exposure_json": args.exposure_json,
            "ledger_json": args.ledger_json,
        },
        "summaries": {
            "pnl": pnl_summary,
            "exposure": exposure_summary,
            "ledger": ledger_summary,
        },
        "checks": [asdict(check) for check in checks],
        "failed_checks": [check.name for check in failed],
    }


def print_table(payload: dict[str, Any]) -> None:
    print("Paper candidate preview invariant audit")
    print(f"audit_version: {payload["audit_version"]}")
    print(f"status: {payload["status"]}")
    print()
    print("--- inputs ---")
    for key, value in payload["inputs"].items():
        print(f"{key}: {value}")
    print()
    print("--- summaries ---")
    print("pnl:", payload["summaries"]["pnl"])
    print("exposure:", payload["summaries"]["exposure"])
    print("ledger:", payload["summaries"]["ledger"])
    print()
    print("--- checks ---")
    for row in payload["checks"]:
        state = "PASS" if row["passed"] else "FAIL"
        print(f"{row["name"]}: {state}")
        if not row["passed"]:
            print(f"  left: {row["left"]}")
            print(f"  right: {row["right"]}")
    print()
    if payload["status"] == "PASS":
        print("AUDIT_PASS: paper candidate preview outputs are internally consistent.")
    else:
        print("AUDIT_FAIL: paper candidate preview outputs are inconsistent.")
        print("failed_checks:", ", ".join(payload["failed_checks"]))


def main() -> int:
    args = parse_args()
    payload = build_payload(args)

    if args.output == "json":
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print_table(payload)

    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
