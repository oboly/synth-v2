from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.common.db import get_connection
from src.reporting.market_breath_live_v1 import build_market_breath_live_by_symbol


DEFAULT_PROFIT_PLAN_ROOT = Path("/var/www/html/synth/accounts")
REPORT_NAME = "run_profit_plan_market_breath_diagnostic_v1"
REPORT_VERSION = "0.1"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only terminal diagnostic for live Profit Plan Market Breath payloads "
            "using the currently published Profit Plan symbol set."
        )
    )
    parser.add_argument("--profile", default=None)
    parser.add_argument("--profit-plan-json", default=None)
    parser.add_argument("--venue", default="bitvavo")
    parser.add_argument("--interval", default="4h")
    parser.add_argument("--lookback-candles", type=int, default=120)
    return parser.parse_args(argv)


def resolve_profit_plan_json_path(*, profile: str | None, profit_plan_json: str | None) -> Path:
    if profit_plan_json:
        return Path(profit_plan_json)
    if not profile:
        raise ValueError("Provide --profile or --profit-plan-json")
    return DEFAULT_PROFIT_PLAN_ROOT / profile / "profit-plan.json"


def load_symbols_from_profit_plan_json(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        str(row.get("symbol") or "").upper()
        for row in payload.get("symbols", [])
        if str(row.get("symbol") or "").strip()
    ]


def _phase_label(row: dict[str, object]) -> str:
    phase = str(row.get("market_breath_phase") or "").upper()
    if phase:
        return phase
    return str(row.get("availability_state") or "UNAVAILABLE").upper()


def render_table(
    *,
    label: str,
    profit_plan_json_path: Path,
    symbols: list[str],
    rows_by_symbol: dict[str, dict[str, object]],
) -> str:
    counts = Counter(_phase_label(rows_by_symbol.get(symbol, {})) for symbol in symbols)
    lines = [
        f"report={REPORT_NAME} version={REPORT_VERSION}",
        f"label={label}",
        f"profit_plan_json={profit_plan_json_path}",
        f"symbols={len(symbols)}",
        "phase_counts=" + " ".join(f"{phase}:{counts[phase]}" for phase in sorted(counts)),
        "",
    ]
    for symbol in symbols:
        row = rows_by_symbol.get(symbol, {})
        raw_scores = row.get("raw_scores") or {}
        failed = row.get("closest_regime_failed_conditions") or []
        failed_text = "; ".join(str(item) for item in failed) if failed else "-"
        lines.append(
            " ".join(
                [
                    f"symbol={symbol}",
                    f"phase={row.get('market_breath_phase') or row.get('availability_state') or 'UNAVAILABLE'}",
                    f"state={row.get('market_breath_state') or '-'}",
                    f"coverage={row.get('market_breath_confidence') if row.get('market_breath_confidence') is not None else '-'}",
                    f"compression={raw_scores.get('compression', '-')}",
                    f"expansion={raw_scores.get('expansion', '-')}",
                    f"momentum={raw_scores.get('momentum', '-')}",
                    f"reversal_pressure={raw_scores.get('reversal_pressure', '-')}",
                    f"relative_strength={raw_scores.get('relative_strength', '-')}",
                    f"closest={row.get('closest_regime_context') or '-'}",
                    f"neutral_reason={json.dumps(row.get('neutral_reason') or '-')}",
                    f"failed={json.dumps(failed_text)}",
                ]
            )
        )
    lines.append("")
    lines.append("db_writes=0 broker_writes=0 order_submission=0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = resolve_profit_plan_json_path(
        profile=args.profile,
        profit_plan_json=args.profit_plan_json,
    )
    symbols = load_symbols_from_profit_plan_json(path)
    if not symbols:
        raise RuntimeError(f"No symbols found in {path}")

    conn = get_connection()
    try:
        rows_by_symbol = build_market_breath_live_by_symbol(
            conn,
            venue=args.venue,
            interval_code=args.interval,
            lookback_candles=args.lookback_candles,
            symbols=symbols,
        )
    finally:
        conn.close()

    label = args.profile or path.parent.name or "profit-plan"
    print(
        render_table(
            label=label,
            profit_plan_json_path=path,
            symbols=symbols,
            rows_by_symbol=rows_by_symbol,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
