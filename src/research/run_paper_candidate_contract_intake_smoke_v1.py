from __future__ import annotations

"""
Synth v2 - Paper Candidate Contract Intake Smoke V1.

LAYER:
research / contract validation smoke

BOUNDARY:
Allowed:
- read contract JSONL from stdin or a file
- validate paper candidate transport objects
- report accepted/rejected contract rows
- fail loudly on malformed boundary payloads

Forbidden:
- account balances
- live positions
- open orders
- execution plans
- broker/order actions
- decision_gate writes
- execution_intent writes
- execution_plan writes
- database writes

Purpose:
Smoke-test the transport boundary between research preview exports and a
future decision_gate adapter without connecting to account-aware layers.
"""

import argparse
import json
import sys
from dataclasses import fields
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.research.paper_candidate_contract_v1 import (
    ResearchPaperCandidateV1,
    validate_candidate,
)



def validation_result_is_valid(result: Any) -> bool:
    for attr_name in ("ok", "valid", "is_valid"):
        if hasattr(result, attr_name):
            return bool(getattr(result, attr_name))

    issues = getattr(result, "issues", None)
    if issues is not None:
        return len(tuple(issues)) == 0

    errors = getattr(result, "errors", None)
    if errors is not None:
        return len(tuple(errors)) == 0

    raise AttributeError(
        "ValidationResult has no ok/valid/is_valid/issues/errors field"
    )


def validation_result_messages(result: Any) -> list[str]:
    issues = getattr(result, "issues", None)
    if issues is not None:
        return [
            getattr(issue, "message", str(issue))
            for issue in tuple(issues)
        ]

    errors = getattr(result, "errors", None)
    if errors is not None:
        return [str(error) for error in tuple(errors)]

    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate paper candidate contract JSONL without DB writes."
    )
    parser.add_argument(
        "--input",
        default="-",
        help="JSONL file path, or '-' for stdin.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=10,
        help="Maximum validation errors to print before stopping.",
    )
    parser.add_argument(
        "--output",
        choices=("summary", "json"),
        default="summary",
    )
    return parser.parse_args()


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def load_lines(input_path: str) -> list[str]:
    if input_path == "-":
        return [line.rstrip("\\n") for line in sys.stdin if line.strip()]
    return [
        line.rstrip("\\n")
        for line in Path(input_path).read_text().splitlines()
        if line.strip()
    ]



def parse_transport_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise TypeError(f"Expected timestamp string, got {type(value).__name__}")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def candidate_from_transport(payload: dict[str, Any]) -> ResearchPaperCandidateV1:
    field_names = {field.name for field in fields(ResearchPaperCandidateV1)}
    unexpected = sorted(set(payload) - field_names)
    if unexpected:
        raise ValueError(f"Unexpected transport fields: {unexpected}")

    return ResearchPaperCandidateV1(
        contract_version=str(payload["contract_version"]),
        policy_name=str(payload["policy_name"]),
        policy_version=str(payload["policy_version"]),
        candidate_state=str(payload["candidate_state"]),
        asset_id=int(payload["asset_id"]),
        symbol=str(payload["symbol"]),
        venue=str(payload["venue"]),
        asof_ts_utc=parse_transport_ts(payload["asof_ts_utc"]),
        selection_state=str(payload["selection_state"]),
        priority_rank=None if payload.get("priority_rank") is None else int(payload["priority_rank"]),
        selection_score=decimal_or_none(payload.get("selection_score")),
        btc_prior_24h=decimal_or_none(payload.get("btc_prior_24h")),
        rotation_bucket=str(payload["rotation_bucket"]),
        classification_code=str(payload["classification_code"]),
        sleeve_fit_code=str(payload["sleeve_fit_code"]),
        simulated_horizon_hours=int(payload["simulated_horizon_hours"]),
        simulated_net_return=decimal_or_none(payload.get("simulated_net_return")),
        source_table=str(payload["source_table"]),
        source_replay_id=None if payload.get("source_replay_id") is None else int(payload["source_replay_id"]),
        notes=None if payload.get("notes") is None else str(payload["notes"]),
    )


def main() -> int:
    args = parse_args()
    lines = load_lines(args.input)

    valid_count = 0
    invalid_count = 0
    errors: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, start=1):
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError("JSONL row must be an object")

            candidate = candidate_from_transport(payload)
            result = validate_candidate(candidate)

            if validation_result_is_valid(result):
                valid_count += 1
                continue

            invalid_count += 1
            errors.append(
                {
                    "line": line_number,
                    "issues": [
                        {
                            "field": issue.field_name,
                            "message": issue.message,
                        }
                        for issue in validation_result_messages(result)
                    ],
                }
            )
        except Exception as exc:
            invalid_count += 1
            errors.append(
                {
                    "line": line_number,
                    "error": str(exc),
                }
            )

        if len(errors) >= args.max_errors:
            break

    summary = {
        "rows_read": len(lines),
        "valid_rows": valid_count,
        "invalid_rows": invalid_count,
        "error_samples": errors,
    }

    if args.output == "json":
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print("Paper candidate contract intake smoke")
        print(f"rows_read={summary['rows_read']}")
        print(f"valid_rows={summary['valid_rows']}")
        print(f"invalid_rows={summary['invalid_rows']}")
        if errors:
            print()
            print("error_samples:")
            for error in errors:
                print(error)

    return 0 if invalid_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
