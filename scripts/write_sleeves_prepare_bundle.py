"""
SYNTH v2
Script: write_sleeves_prepare_bundle
Purpose:
    Write the sleeves + PREPARE + paper PnL bundle files to disk.
Usage:
    python -m scripts.write_sleeves_prepare_bundle
Notes:
    - Safe to rerun
    - Overwrites target files
"""

from __future__ import annotations

from pathlib import Path


FILES: dict[str, str] = {
    "docs/sleeves_prepare_pnl_bundle.md": r"""# SYNTH v2 — Sleeves + PREPARE + Paper PnL Bundle

## Goal
Add:
- PREPARE state between WATCH and ENTER_LONG
- portfolio sleeves
- default sleeve agents
- lot-based paper accounting
- strategy attribution and daily metrics
- clean flow through:
  selection -> sleeve agents -> decision -> risk -> portfolio -> execution_intent

## Canonical sleeves
- CORE         = 0.30
- SWING        = 0.35
- TACTICAL     = 0.25
- EXPERIMENTAL = 0.10

## Canonical agent defaults
- CORE         -> core_trend
- SWING        -> swing_rotation
- TACTICAL     -> tactical_momentum
- EXPERIMENTAL -> experimental_misc

## Canonical state ladders
CORE / SWING:
- WATCH -> PREPARE -> ENTER_LONG -> HOLD -> REDUCE -> EXIT

TACTICAL:
- WATCH -> SCALP_ONLY -> HOLD -> EXIT

## Key design rules
1. Sleeves own capital budgets.
2. Agents propose; allocator approves.
3. PREPARE belongs to structural sleeves, not tactical.
4. Lots are the accounting unit.
5. Paper execution updates lots using target deltas.
6. Market response can be fast; strategy review stays slow/versioned.

## Fast loop
Recommended every market refresh / minute:
- read latest signals
- run sleeve agents
- allocate targets
- write decision / risk / portfolio targets
- generate execution intents
- update paper positions and snapshots

## Slow loop
Recommended daily aggregation:
- realized PnL
- unrealized PnL
- per-sleeve metrics
- per-strategy metrics
- PREPARE transition success / failure

## Important v1 simplification
This bundle does not assume live exchange fills.
Paper execution uses:
- latest price
- target fraction delta
- wallet equity in EUR

That is enough to build the accounting backbone now.
""",
    "configs/portfolio_sleeves.yaml": r"""version: 1

portfolio:
  currency: EUR
  wallet_equity_source: PAPER
  market_loop_seconds: 60

sleeves:
  CORE:
    wallet_share: 0.30
    max_positions: 3
    per_position_cap: 0.15
    allowed_actions: [PREPARE, ENTER_LONG, HOLD, REDUCE, EXIT]
    agent_names: [core_trend]
    prepare:
      enabled: true
      cap: 0.20
      max_positions: 2

  SWING:
    wallet_share: 0.35
    max_positions: 6
    per_position_cap: 0.05
    allowed_actions: [PREPARE, ENTER_LONG, HOLD, REDUCE, EXIT]
    agent_names: [swing_rotation]
    prepare:
      enabled: true
      cap: 0.20
      max_positions: 3

  TACTICAL:
    wallet_share: 0.25
    max_positions: 3
    per_position_cap: 0.08
    allowed_actions: [SCALP_ONLY, HOLD, EXIT]
    agent_names: [tactical_momentum]
    prepare:
      enabled: false
      cap: 0.00
      max_positions: 0

  EXPERIMENTAL:
    wallet_share: 0.10
    max_positions: 2
    per_position_cap: 0.05
    allowed_actions: [PREPARE, SCALP_ONLY, ENTER_LONG, HOLD, EXIT]
    agent_names: [experimental_misc]
    prepare:
      enabled: true
      cap: 0.10
      max_positions: 1

strategy_review:
  metrics_rollup_days:
    tactical: 7
    swing: 14
    core: 30
    experimental: 14

paper_execution:
  min_trade_fraction: 0.0050
  snapshot_every_loop: true
  close_when_target_fraction_below: 0.0001
""",
    "src/synth_sleeves/models.py": r'''"""
SYNTH v2
Module: synth_sleeves.models
Purpose:
    Canonical dataclasses and enums for sleeve-aware targeting, PREPARE, and paper lots.
Boundary:
    - No DB I/O here
    - No exchange I/O here
    - Pure in-memory contracts only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


DECIMAL_ZERO = Decimal("0")
DECIMAL_ONE = Decimal("1")


class SleeveCode(str, Enum):
    CORE = "CORE"
    SWING = "SWING"
    TACTICAL = "TACTICAL"
    EXPERIMENTAL = "EXPERIMENTAL"


class DecisionAction(str, Enum):
    AVOID = "AVOID"
    WATCH = "WATCH"
    PREPARE = "PREPARE"
    SCALP_ONLY = "SCALP_ONLY"
    ENTER_LONG = "ENTER_LONG"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    BLOCK = "BLOCK"


class EntryState(str, Enum):
    WATCH = "WATCH"
    PREPARE = "PREPARE"
    ENTER_LONG = "ENTER_LONG"
    SCALP_ONLY = "SCALP_ONLY"


@dataclass(slots=True)
class AgentSignalRow:
    asset_id: int
    symbol: str
    selection_state: str
    selection_score: Decimal
    selection_bias: str
    decision_hint: str | None = None
    regime_ok: bool = True
    htf_reject: bool = False
    liquidity_ok: bool = True
    latest_price_eur: Decimal = DECIMAL_ZERO
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentProposal:
    run_ts_utc: datetime
    asset_id: int
    symbol: str
    sleeve_code: SleeveCode
    strategy_name: str
    desired_action: DecisionAction
    requested_fraction: Decimal
    score: Decimal
    source_state: str
    reasoning: str
    latest_price_eur: Decimal
    entry_state: EntryState | None = None


@dataclass(slots=True)
class ApprovedTarget:
    run_ts_utc: datetime
    asset_id: int
    symbol: str
    sleeve_code: SleeveCode
    strategy_name: str
    desired_action: DecisionAction
    target_fraction: Decimal
    decision_strength: str
    source_state: str
    reasoning: str
    latest_price_eur: Decimal


@dataclass(slots=True)
class OpenLot:
    position_lot_id: int
    asset_id: int
    sleeve_code: SleeveCode
    strategy_name: str
    entry_state: EntryState
    open_ts_utc: datetime
    entry_price_eur: Decimal
    latest_price_eur: Decimal
    current_fraction: Decimal
    entry_notional_eur: Decimal
    current_notional_eur: Decimal
    quantity_units: Decimal
    realized_pnl_eur: Decimal = DECIMAL_ZERO
    unrealized_pnl_eur: Decimal = DECIMAL_ZERO
    entry_reason: str = ""
    last_transition_state: str | None = None


@dataclass(slots=True)
class PaperFillIntent:
    run_ts_utc: datetime
    asset_id: int
    symbol: str
    sleeve_code: SleeveCode
    strategy_name: str
    action: str
    delta_fraction: Decimal
    price_eur: Decimal
    reasoning: str


@dataclass(slots=True)
class SleeveConfig:
    sleeve_code: SleeveCode
    wallet_share: Decimal
    max_positions: int
    per_position_cap: Decimal
    allowed_actions: set[DecisionAction]
    agent_names: list[str]
    prepare_enabled: bool
    prepare_cap: Decimal
    prepare_max_positions: int
''',
    "src/synth_sleeves/config_loader.py": r'''"""
SYNTH v2
Module: synth_sleeves.config_loader
Purpose:
    Load sleeve configuration from YAML into typed config objects.
Boundary:
    - File I/O allowed
    - No DB I/O
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

from src.synth_sleeves.models import DecisionAction, SleeveCode, SleeveConfig


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def load_sleeve_config(config_path: str | Path) -> dict[SleeveCode, SleeveConfig]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    result: dict[SleeveCode, SleeveConfig] = {}
    for sleeve_name, sleeve_raw in raw["sleeves"].items():
        sleeve_code = SleeveCode(sleeve_name)
        result[sleeve_code] = SleeveConfig(
            sleeve_code=sleeve_code,
            wallet_share=_to_decimal(sleeve_raw["wallet_share"]),
            max_positions=int(sleeve_raw["max_positions"]),
            per_position_cap=_to_decimal(sleeve_raw["per_position_cap"]),
            allowed_actions={DecisionAction(x) for x in sleeve_raw["allowed_actions"]},
            agent_names=list(sleeve_raw["agent_names"]),
            prepare_enabled=bool(sleeve_raw["prepare"]["enabled"]),
            prepare_cap=_to_decimal(sleeve_raw["prepare"]["cap"]),
            prepare_max_positions=int(sleeve_raw["prepare"]["max_positions"]),
        )

    wallet_total = sum((cfg.wallet_share for cfg in result.values()), start=Decimal("0"))
    if wallet_total != Decimal("1.00"):
        raise ValueError(f"Expected total wallet_share == 1.00, got {wallet_total}")

    return result
''',
    "src/synth_sleeves/strategy_versioning.py": r'''"""
SYNTH v2
Module: synth_sleeves.strategy_versioning
Purpose:
    Deterministic strategy version hash generation.
Boundary:
    - Pure utility
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def make_strategy_version_hash(strategy_name: str, config_payload: dict[str, Any]) -> str:
    payload = {
        "strategy_name": strategy_name,
        "config_payload": config_payload,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_strategy_version_label(strategy_name: str, version_hash: str) -> str:
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{strategy_name}:{now_utc}:{version_hash[:12]}"
''',
    "src/synth_sleeves/agents.py": r'''"""
SYNTH v2
Module: synth_sleeves.agents
Purpose:
    Default v1 sleeve agents.
Boundary:
    - No DB I/O
    - No external API I/O
    - Input = normalized selection rows
    - Output = proposals only
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.synth_sleeves.models import (
    AgentProposal,
    AgentSignalRow,
    DecisionAction,
    EntryState,
    SleeveCode,
)


PRE_ALIGNMENT_STATES = {
    "PRE_ALIGNMENT",
    "EARLY_WATCH",
    "COMPRESSION_BUILD",
}
CORE_ENTER_STATES = {
    "ENTER_LONG",
    "LONG_READY",
    "CONFIRMED_LONG",
}
TACTICAL_STATES = {
    "SCALP_ONLY",
    "TACTICAL",
    "TACTICAL_LONG",
}


def core_trend(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if row.htf_reject or not row.liquidity_ok:
        return None

    if row.selection_state in CORE_ENTER_STATES and row.regime_ok:
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction.ENTER_LONG,
            requested_fraction=Decimal("0.15"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE enter-ready structural alignment.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if row.selection_state in PRE_ALIGNMENT_STATES and row.regime_ok:
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.CORE,
            strategy_name="core_trend",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=Decimal("0.20"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="CORE prepare: early structural alignment before confirmation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    return None


def swing_rotation(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if row.htf_reject or not row.liquidity_ok:
        return None

    if row.selection_state in CORE_ENTER_STATES and row.regime_ok:
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction.ENTER_LONG,
            requested_fraction=Decimal("0.05"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING enter-ready rotation setup.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if row.selection_state in PRE_ALIGNMENT_STATES and row.selection_score >= Decimal("0.45") and row.regime_ok:
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.SWING,
            strategy_name="swing_rotation",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=Decimal("0.05"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="SWING prepare: constructive multi-day setup before confirmation.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    return None


def tactical_momentum(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if not row.liquidity_ok:
        return None

    if row.selection_state in TACTICAL_STATES and row.selection_score >= Decimal("0.50"):
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.TACTICAL,
            strategy_name="tactical_momentum",
            desired_action=DecisionAction.SCALP_ONLY,
            requested_fraction=Decimal("0.08"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="TACTICAL momentum burst / short-lived edge.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.SCALP_ONLY,
        )

    return None


def experimental_misc(run_ts_utc: datetime, row: AgentSignalRow) -> AgentProposal | None:
    if row.htf_reject:
        return None

    if row.selection_state in CORE_ENTER_STATES and row.selection_score >= Decimal("0.55"):
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.EXPERIMENTAL,
            strategy_name="experimental_misc",
            desired_action=DecisionAction.ENTER_LONG,
            requested_fraction=Decimal("0.05"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="EXPERIMENTAL enter-ready candidate.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.ENTER_LONG,
        )

    if row.selection_state in PRE_ALIGNMENT_STATES and row.selection_score >= Decimal("0.50"):
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.EXPERIMENTAL,
            strategy_name="experimental_misc",
            desired_action=DecisionAction.PREPARE,
            requested_fraction=Decimal("0.05"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="EXPERIMENTAL prepare candidate.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.PREPARE,
        )

    if row.selection_state in TACTICAL_STATES and row.selection_score >= Decimal("0.60"):
        return AgentProposal(
            run_ts_utc=run_ts_utc,
            asset_id=row.asset_id,
            symbol=row.symbol,
            sleeve_code=SleeveCode.EXPERIMENTAL,
            strategy_name="experimental_misc",
            desired_action=DecisionAction.SCALP_ONLY,
            requested_fraction=Decimal("0.05"),
            score=row.selection_score,
            source_state=row.selection_state,
            reasoning="EXPERIMENTAL tactical candidate.",
            latest_price_eur=row.latest_price_eur,
            entry_state=EntryState.SCALP_ONLY,
        )

    return None


AGENT_REGISTRY = {
    "core_trend": core_trend,
    "swing_rotation": swing_rotation,
    "tactical_momentum": tactical_momentum,
    "experimental_misc": experimental_misc,
}
''',
    "src/synth_sleeves/allocator.py": r'''"""
SYNTH v2
Module: synth_sleeves.allocator
Purpose:
    Convert proposals into approved sleeve targets.
Boundary:
    - No DB I/O
    - No exchange I/O
    - Deterministic ranking and capping
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_DOWN

from src.synth_sleeves.models import ApprovedTarget, AgentProposal, DecisionAction, SleeveCode, SleeveConfig


DECIMAL_ZERO = Decimal("0")
Q8 = Decimal("0.00000001")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Q8, rounding=ROUND_DOWN)


def allocate_targets(
    proposals: list[AgentProposal],
    sleeve_config: dict[SleeveCode, SleeveConfig],
) -> list[ApprovedTarget]:
    grouped: dict[SleeveCode, list[AgentProposal]] = defaultdict(list)
    for proposal in proposals:
        grouped[proposal.sleeve_code].append(proposal)

    approved: list[ApprovedTarget] = []

    for sleeve_code, items in grouped.items():
        cfg = sleeve_config[sleeve_code]
        ranked = sorted(items, key=lambda x: (x.score, x.asset_id), reverse=True)

        used_budget = DECIMAL_ZERO
        used_positions = 0
        used_prepare_positions = 0

        for item in ranked:
            if item.desired_action not in cfg.allowed_actions:
                continue
            if used_positions >= cfg.max_positions:
                break

            raw_target = min(item.requested_fraction, cfg.per_position_cap)

            if item.desired_action == DecisionAction.PREPARE:
                if not cfg.prepare_enabled:
                    continue
                if used_prepare_positions >= cfg.prepare_max_positions:
                    continue
                raw_target = min(raw_target, cfg.prepare_cap)

            remaining_budget = cfg.wallet_share - used_budget
            if remaining_budget <= DECIMAL_ZERO:
                break

            target_fraction = _q(min(raw_target, remaining_budget))
            if target_fraction <= DECIMAL_ZERO:
                continue

            approved.append(
                ApprovedTarget(
                    run_ts_utc=item.run_ts_utc,
                    asset_id=item.asset_id,
                    symbol=item.symbol,
                    sleeve_code=item.sleeve_code,
                    strategy_name=item.strategy_name,
                    desired_action=item.desired_action,
                    target_fraction=target_fraction,
                    decision_strength=_strength_from_action(item.desired_action),
                    source_state=item.source_state,
                    reasoning=item.reasoning,
                    latest_price_eur=item.latest_price_eur,
                )
            )

            used_budget += target_fraction
            used_positions += 1
            if item.desired_action == DecisionAction.PREPARE:
                used_prepare_positions += 1

    return approved


def _strength_from_action(action: DecisionAction) -> str:
    if action == DecisionAction.PREPARE:
        return "MEDIUM"
    if action in {DecisionAction.ENTER_LONG, DecisionAction.SCALP_ONLY}:
        return "HIGH"
    if action in {DecisionAction.REDUCE, DecisionAction.EXIT, DecisionAction.BLOCK}:
        return "HIGH"
    return "LOW"
''',
    "src/synth_sleeves/risk_policy.py": r'''"""
SYNTH v2
Module: synth_sleeves.risk_policy
Purpose:
    Apply v1 state/risk clamping for PREPARE and sleeve actions.
Boundary:
    - No DB I/O
    - Stateless
"""

from __future__ import annotations

from decimal import Decimal

from src.synth_sleeves.models import ApprovedTarget, DecisionAction, SleeveCode, SleeveConfig


DECIMAL_ZERO = Decimal("0")


def apply_risk_policy(
    targets: list[ApprovedTarget],
    sleeve_config: dict[SleeveCode, SleeveConfig],
) -> list[ApprovedTarget]:
    result: list[ApprovedTarget] = []

    for target in targets:
        cfg = sleeve_config[target.sleeve_code]
        clamped = target.target_fraction

        if target.desired_action == DecisionAction.PREPARE:
            clamped = min(clamped, cfg.prepare_cap)

        if target.desired_action == DecisionAction.SCALP_ONLY:
            clamped = min(clamped, cfg.per_position_cap)

        if clamped <= DECIMAL_ZERO:
            continue

        result.append(
            ApprovedTarget(
                run_ts_utc=target.run_ts_utc,
                asset_id=target.asset_id,
                symbol=target.symbol,
                sleeve_code=target.sleeve_code,
                strategy_name=target.strategy_name,
                desired_action=target.desired_action,
                target_fraction=clamped,
                decision_strength=target.decision_strength,
                source_state=target.source_state,
                reasoning=target.reasoning,
                latest_price_eur=target.latest_price_eur,
            )
        )

    return result
''',
    "src/synth_sleeves/paper_pnl.py": r'''"""
SYNTH v2
Module: synth_sleeves.paper_pnl
Purpose:
    Lot-based paper accounting engine.
Boundary:
    - No strategy logic here
    - Applies target deltas to lots
    - Uses EUR wallet equity + latest EUR prices
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from src.synth_sleeves.models import (
    ApprovedTarget,
    DecisionAction,
    EntryState,
    OpenLot,
    PaperFillIntent,
    SleeveCode,
)


DECIMAL_ZERO = Decimal("0")
Q8 = Decimal("0.00000001")
Q10 = Decimal("0.0000000001")
Q18 = Decimal("0.000000000000000001")


def q8(value: Decimal) -> Decimal:
    return value.quantize(Q8, rounding=ROUND_HALF_UP)


def q10(value: Decimal) -> Decimal:
    return value.quantize(Q10, rounding=ROUND_HALF_UP)


def q18(value: Decimal) -> Decimal:
    return value.quantize(Q18, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class TargetDelta:
    target: ApprovedTarget
    current_fraction: Decimal
    delta_fraction: Decimal


def build_fill_intents(
    targets: list[ApprovedTarget],
    open_lots: Iterable[OpenLot],
    min_trade_fraction: Decimal,
) -> list[PaperFillIntent]:
    current_by_key: dict[tuple[int, SleeveCode], Decimal] = {}
    for lot in open_lots:
        key = (lot.asset_id, lot.sleeve_code)
        current_by_key[key] = current_by_key.get(key, DECIMAL_ZERO) + lot.current_fraction

    intents: list[PaperFillIntent] = []
    seen_keys: set[tuple[int, SleeveCode]] = set()

    for target in targets:
        key = (target.asset_id, target.sleeve_code)
        seen_keys.add(key)
        current_fraction = current_by_key.get(key, DECIMAL_ZERO)
        delta = q8(target.target_fraction - current_fraction)

        if abs(delta) < min_trade_fraction:
            continue

        if delta > DECIMAL_ZERO:
            action = "OPEN" if current_fraction <= DECIMAL_ZERO else "ADD"
        else:
            action = "CLOSE" if target.target_fraction <= DECIMAL_ZERO else "REDUCE"

        intents.append(
            PaperFillIntent(
                run_ts_utc=target.run_ts_utc,
                asset_id=target.asset_id,
                symbol=target.symbol,
                sleeve_code=target.sleeve_code,
                strategy_name=target.strategy_name,
                action=action,
                delta_fraction=delta,
                price_eur=target.latest_price_eur,
                reasoning=target.reasoning,
            )
        )

    for lot in open_lots:
        key = (lot.asset_id, lot.sleeve_code)
        if key in seen_keys:
            continue
        if lot.current_fraction <= DECIMAL_ZERO:
            continue
        intents.append(
            PaperFillIntent(
                run_ts_utc=lot.open_ts_utc,
                asset_id=lot.asset_id,
                symbol=f"asset_{lot.asset_id}",
                sleeve_code=lot.sleeve_code,
                strategy_name=lot.strategy_name,
                action="CLOSE",
                delta_fraction=q8(-lot.current_fraction),
                price_eur=lot.latest_price_eur,
                reasoning="No remaining target for sleeve/asset pair.",
            )
        )

    return intents


def open_new_lot(
    *,
    next_position_lot_id: int,
    run_ts_utc: datetime,
    asset_id: int,
    sleeve_code: SleeveCode,
    strategy_name: str,
    entry_state: EntryState,
    price_eur: Decimal,
    target_fraction: Decimal,
    wallet_equity_eur: Decimal,
    entry_reason: str,
) -> OpenLot:
    entry_notional = q10(wallet_equity_eur * target_fraction)
    quantity = q18(entry_notional / price_eur) if price_eur > DECIMAL_ZERO else DECIMAL_ZERO
    return OpenLot(
        position_lot_id=next_position_lot_id,
        asset_id=asset_id,
        sleeve_code=sleeve_code,
        strategy_name=strategy_name,
        entry_state=entry_state,
        open_ts_utc=run_ts_utc,
        entry_price_eur=q10(price_eur),
        latest_price_eur=q10(price_eur),
        current_fraction=q8(target_fraction),
        entry_notional_eur=entry_notional,
        current_notional_eur=entry_notional,
        quantity_units=quantity,
        entry_reason=entry_reason,
    )


def mark_to_market(lot: OpenLot, latest_price_eur: Decimal, wallet_equity_eur: Decimal) -> OpenLot:
    current_notional = q10(wallet_equity_eur * lot.current_fraction)
    quantity = lot.quantity_units
    market_value = q10(quantity * latest_price_eur)
    unrealized = q10(market_value - lot.entry_notional_eur)
    return OpenLot(
        position_lot_id=lot.position_lot_id,
        asset_id=lot.asset_id,
        sleeve_code=lot.sleeve_code,
        strategy_name=lot.strategy_name,
        entry_state=lot.entry_state,
        open_ts_utc=lot.open_ts_utc,
        entry_price_eur=lot.entry_price_eur,
        latest_price_eur=q10(latest_price_eur),
        current_fraction=lot.current_fraction,
        entry_notional_eur=lot.entry_notional_eur,
        current_notional_eur=current_notional,
        quantity_units=quantity,
        realized_pnl_eur=lot.realized_pnl_eur,
        unrealized_pnl_eur=unrealized,
        entry_reason=lot.entry_reason,
        last_transition_state=lot.last_transition_state,
    )


def reduce_lot_fraction(lot: OpenLot, reduce_fraction: Decimal, price_eur: Decimal) -> tuple[OpenLot, Decimal]:
    if reduce_fraction <= DECIMAL_ZERO:
        return lot, DECIMAL_ZERO
    if reduce_fraction > lot.current_fraction:
        reduce_fraction = lot.current_fraction

    exit_ratio = reduce_fraction / lot.current_fraction if lot.current_fraction > DECIMAL_ZERO else DECIMAL_ZERO
    exited_units = q18(lot.quantity_units * exit_ratio)
    exit_notional = q10(exited_units * price_eur)
    cost_basis = q10(lot.entry_notional_eur * exit_ratio)
    realized = q10(exit_notional - cost_basis)

    remaining_fraction = q8(lot.current_fraction - reduce_fraction)
    remaining_units = q18(lot.quantity_units - exited_units)
    remaining_entry_notional = q10(lot.entry_notional_eur - cost_basis)

    updated = OpenLot(
        position_lot_id=lot.position_lot_id,
        asset_id=lot.asset_id,
        sleeve_code=lot.sleeve_code,
        strategy_name=lot.strategy_name,
        entry_state=lot.entry_state,
        open_ts_utc=lot.open_ts_utc,
        entry_price_eur=lot.entry_price_eur,
        latest_price_eur=q10(price_eur),
        current_fraction=remaining_fraction,
        entry_notional_eur=remaining_entry_notional,
        current_notional_eur=q10(exit_notional if remaining_fraction <= DECIMAL_ZERO else remaining_units * price_eur),
        quantity_units=remaining_units,
        realized_pnl_eur=q10(lot.realized_pnl_eur + realized),
        unrealized_pnl_eur=DECIMAL_ZERO,
        entry_reason=lot.entry_reason,
        last_transition_state=lot.last_transition_state,
    )
    return updated, realized


def target_to_entry_state(action: DecisionAction) -> EntryState:
    if action == DecisionAction.PREPARE:
        return EntryState.PREPARE
    if action == DecisionAction.SCALP_ONLY:
        return EntryState.SCALP_ONLY
    return EntryState.ENTER_LONG
''',
    "src/synth_sleeves/db_repository.py": r'''"""
SYNTH v2
Module: synth_sleeves.db_repository
Purpose:
    MariaDB repository for sleeve targets, lots, trades, snapshots, metrics.
Boundary:
    - DB only
    - No strategy logic
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.synth_sleeves.models import ApprovedTarget, OpenLot, SleeveCode


class SleeveRepository:
    def __init__(self, connection_params: dict[str, Any]) -> None:
        self._connection_params = connection_params

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(
            cursorclass=DictCursor,
            autocommit=False,
            charset="utf8mb4",
            **self._connection_params,
        )

    def fetch_open_lots(self) -> list[OpenLot]:
        sql = """
        SELECT
            position_lot_id,
            asset_id,
            sleeve_code,
            strategy_name,
            entry_state,
            open_ts_utc,
            entry_price_eur,
            COALESCE(latest_price_eur, entry_price_eur) AS latest_price_eur,
            current_fraction,
            entry_notional_eur,
            current_notional_eur,
            quantity_units,
            realized_pnl_eur,
            unrealized_pnl_eur,
            COALESCE(entry_reason, '') AS entry_reason,
            last_transition_state
        FROM position_lot
        WHERE status = 'OPEN'
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        result: list[OpenLot] = []
        for row in rows:
            result.append(
                OpenLot(
                    position_lot_id=int(row["position_lot_id"]),
                    asset_id=int(row["asset_id"]),
                    sleeve_code=SleeveCode(row["sleeve_code"]),
                    strategy_name=str(row["strategy_name"]),
                    entry_state=row["entry_state"],
                    open_ts_utc=row["open_ts_utc"],
                    entry_price_eur=Decimal(str(row["entry_price_eur"])),
                    latest_price_eur=Decimal(str(row["latest_price_eur"])),
                    current_fraction=Decimal(str(row["current_fraction"])),
                    entry_notional_eur=Decimal(str(row["entry_notional_eur"])),
                    current_notional_eur=Decimal(str(row["current_notional_eur"])),
                    quantity_units=Decimal(str(row["quantity_units"])),
                    realized_pnl_eur=Decimal(str(row["realized_pnl_eur"])),
                    unrealized_pnl_eur=Decimal(str(row["unrealized_pnl_eur"])),
                    entry_reason=str(row["entry_reason"]),
                    last_transition_state=row["last_transition_state"],
                )
            )
        return result

    def insert_portfolio_targets(self, targets: list[ApprovedTarget], strategy_version_lookup: dict[str, int]) -> None:
        if not targets:
            return

        sql = """
        INSERT INTO portfolio_target (
            run_ts_utc,
            asset_id,
            sleeve_code,
            strategy_name,
            strategy_version_id,
            desired_action,
            target_fraction,
            decision_strength,
            reasoning,
            source_state,
            current_price_eur
        ) VALUES (
            %(run_ts_utc)s,
            %(asset_id)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(strategy_version_id)s,
            %(desired_action)s,
            %(target_fraction)s,
            %(decision_strength)s,
            %(reasoning)s,
            %(source_state)s,
            %(current_price_eur)s
        )
        ON DUPLICATE KEY UPDATE
            strategy_name = VALUES(strategy_name),
            strategy_version_id = VALUES(strategy_version_id),
            desired_action = VALUES(desired_action),
            target_fraction = VALUES(target_fraction),
            decision_strength = VALUES(decision_strength),
            reasoning = VALUES(reasoning),
            source_state = VALUES(source_state),
            current_price_eur = VALUES(current_price_eur)
        """
        payload = []
        for item in targets:
            payload.append(
                {
                    "run_ts_utc": item.run_ts_utc,
                    "asset_id": item.asset_id,
                    "sleeve_code": item.sleeve_code.value,
                    "strategy_name": item.strategy_name,
                    "strategy_version_id": strategy_version_lookup.get(item.strategy_name),
                    "desired_action": item.desired_action.value,
                    "target_fraction": str(item.target_fraction),
                    "decision_strength": item.decision_strength,
                    "reasoning": item.reasoning,
                    "source_state": item.source_state,
                    "current_price_eur": str(item.latest_price_eur),
                }
            )

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, payload)
            conn.commit()

    def upsert_open_lot(self, lot: OpenLot) -> None:
        sql = """
        INSERT INTO position_lot (
            position_lot_id,
            asset_id,
            sleeve_code,
            strategy_name,
            entry_state,
            status,
            open_ts_utc,
            entry_price_eur,
            latest_price_eur,
            target_fraction_at_open,
            current_fraction,
            entry_notional_eur,
            current_notional_eur,
            realized_pnl_eur,
            unrealized_pnl_eur,
            quantity_units,
            entry_reason,
            last_transition_state,
            last_update_ts_utc
        ) VALUES (
            %(position_lot_id)s,
            %(asset_id)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(entry_state)s,
            'OPEN',
            %(open_ts_utc)s,
            %(entry_price_eur)s,
            %(latest_price_eur)s,
            %(current_fraction)s,
            %(current_fraction)s,
            %(entry_notional_eur)s,
            %(current_notional_eur)s,
            %(realized_pnl_eur)s,
            %(unrealized_pnl_eur)s,
            %(quantity_units)s,
            %(entry_reason)s,
            %(last_transition_state)s,
            UTC_TIMESTAMP()
        )
        ON DUPLICATE KEY UPDATE
            latest_price_eur = VALUES(latest_price_eur),
            current_fraction = VALUES(current_fraction),
            current_notional_eur = VALUES(current_notional_eur),
            realized_pnl_eur = VALUES(realized_pnl_eur),
            unrealized_pnl_eur = VALUES(unrealized_pnl_eur),
            quantity_units = VALUES(quantity_units),
            last_transition_state = VALUES(last_transition_state),
            last_update_ts_utc = UTC_TIMESTAMP()
        """
        payload = {
            "position_lot_id": lot.position_lot_id,
            "asset_id": lot.asset_id,
            "sleeve_code": lot.sleeve_code.value,
            "strategy_name": lot.strategy_name,
            "entry_state": str(lot.entry_state),
            "open_ts_utc": lot.open_ts_utc,
            "entry_price_eur": str(lot.entry_price_eur),
            "latest_price_eur": str(lot.latest_price_eur),
            "current_fraction": str(lot.current_fraction),
            "entry_notional_eur": str(lot.entry_notional_eur),
            "current_notional_eur": str(lot.current_notional_eur),
            "realized_pnl_eur": str(lot.realized_pnl_eur),
            "unrealized_pnl_eur": str(lot.unrealized_pnl_eur),
            "quantity_units": str(lot.quantity_units),
            "entry_reason": lot.entry_reason,
            "last_transition_state": lot.last_transition_state,
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
            conn.commit()

    def close_lot(self, lot: OpenLot, close_ts_utc: datetime, exit_price_eur: Decimal, exit_reason: str, exit_state: str) -> None:
        holding_minutes = int((close_ts_utc - lot.open_ts_utc).total_seconds() // 60)
        realized_pct = Decimal("0")
        if lot.entry_notional_eur != Decimal("0"):
            realized_pct = (lot.realized_pnl_eur / lot.entry_notional_eur) * Decimal("100")

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE position_lot
                    SET
                        status = 'CLOSED',
                        close_ts_utc = %(close_ts_utc)s,
                        latest_price_eur = %(exit_price_eur)s,
                        current_fraction = 0,
                        current_notional_eur = 0,
                        unrealized_pnl_eur = 0,
                        exit_reason = %(exit_reason)s,
                        last_transition_state = %(exit_state)s,
                        last_update_ts_utc = UTC_TIMESTAMP()
                    WHERE position_lot_id = %(position_lot_id)s
                    """,
                    {
                        "close_ts_utc": close_ts_utc,
                        "exit_price_eur": str(exit_price_eur),
                        "exit_reason": exit_reason,
                        "exit_state": exit_state,
                        "position_lot_id": lot.position_lot_id,
                    },
                )
                cur.execute(
                    """
                    INSERT INTO trade_lot (
                        position_lot_id,
                        asset_id,
                        sleeve_code,
                        strategy_name,
                        entry_state,
                        exit_state,
                        open_ts_utc,
                        close_ts_utc,
                        entry_price_eur,
                        exit_price_eur,
                        entry_notional_eur,
                        exit_notional_eur,
                        quantity_units,
                        realized_pnl_eur,
                        realized_pnl_pct,
                        holding_minutes,
                        entry_reason,
                        exit_reason
                    ) VALUES (
                        %(position_lot_id)s,
                        %(asset_id)s,
                        %(sleeve_code)s,
                        %(strategy_name)s,
                        %(entry_state)s,
                        %(exit_state)s,
                        %(open_ts_utc)s,
                        %(close_ts_utc)s,
                        %(entry_price_eur)s,
                        %(exit_price_eur)s,
                        %(entry_notional_eur)s,
                        %(exit_notional_eur)s,
                        %(quantity_units)s,
                        %(realized_pnl_eur)s,
                        %(realized_pnl_pct)s,
                        %(holding_minutes)s,
                        %(entry_reason)s,
                        %(exit_reason)s
                    )
                    """,
                    {
                        "position_lot_id": lot.position_lot_id,
                        "asset_id": lot.asset_id,
                        "sleeve_code": lot.sleeve_code.value,
                        "strategy_name": lot.strategy_name,
                        "entry_state": str(lot.entry_state),
                        "exit_state": exit_state,
                        "open_ts_utc": lot.open_ts_utc,
                        "close_ts_utc": close_ts_utc,
                        "entry_price_eur": str(lot.entry_price_eur),
                        "exit_price_eur": str(exit_price_eur),
                        "entry_notional_eur": str(lot.entry_notional_eur),
                        "exit_notional_eur": str(lot.quantity_units * exit_price_eur),
                        "quantity_units": str(lot.quantity_units),
                        "realized_pnl_eur": str(lot.realized_pnl_eur),
                        "realized_pnl_pct": str(realized_pct),
                        "holding_minutes": holding_minutes,
                        "entry_reason": lot.entry_reason,
                        "exit_reason": exit_reason,
                    },
                )
            conn.commit()

    def insert_snapshot(self, snapshot_ts_utc: datetime, lot: OpenLot) -> None:
        sql = """
        INSERT INTO position_snapshot (
            snapshot_ts_utc,
            position_lot_id,
            asset_id,
            sleeve_code,
            strategy_name,
            entry_state,
            status,
            latest_price_eur,
            current_fraction,
            current_notional_eur,
            realized_pnl_eur,
            unrealized_pnl_eur
        ) VALUES (
            %(snapshot_ts_utc)s,
            %(position_lot_id)s,
            %(asset_id)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(entry_state)s,
            'OPEN',
            %(latest_price_eur)s,
            %(current_fraction)s,
            %(current_notional_eur)s,
            %(realized_pnl_eur)s,
            %(unrealized_pnl_eur)s
        )
        ON DUPLICATE KEY UPDATE
            latest_price_eur = VALUES(latest_price_eur),
            current_fraction = VALUES(current_fraction),
            current_notional_eur = VALUES(current_notional_eur),
            realized_pnl_eur = VALUES(realized_pnl_eur),
            unrealized_pnl_eur = VALUES(unrealized_pnl_eur)
        """
        payload = {
            "snapshot_ts_utc": snapshot_ts_utc,
            "position_lot_id": lot.position_lot_id,
            "asset_id": lot.asset_id,
            "sleeve_code": lot.sleeve_code.value,
            "strategy_name": lot.strategy_name,
            "entry_state": str(lot.entry_state),
            "latest_price_eur": str(lot.latest_price_eur),
            "current_fraction": str(lot.current_fraction),
            "current_notional_eur": str(lot.current_notional_eur),
            "realized_pnl_eur": str(lot.realized_pnl_eur),
            "unrealized_pnl_eur": str(lot.unrealized_pnl_eur),
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, payload)
            conn.commit()

    def insert_or_update_strategy_metrics_daily(self, row: dict[str, Any]) -> None:
        sql = """
        INSERT INTO strategy_metrics_daily (
            metric_date_utc,
            sleeve_code,
            strategy_name,
            strategy_version_id,
            trades_closed,
            wins,
            losses,
            win_rate,
            avg_realized_pnl_pct,
            avg_realized_pnl_eur,
            gross_profit_eur,
            gross_loss_eur,
            profit_factor,
            avg_holding_minutes,
            prepare_to_enter_count,
            prepare_fail_count
        ) VALUES (
            %(metric_date_utc)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(strategy_version_id)s,
            %(trades_closed)s,
            %(wins)s,
            %(losses)s,
            %(win_rate)s,
            %(avg_realized_pnl_pct)s,
            %(avg_realized_pnl_eur)s,
            %(gross_profit_eur)s,
            %(gross_loss_eur)s,
            %(profit_factor)s,
            %(avg_holding_minutes)s,
            %(prepare_to_enter_count)s,
            %(prepare_fail_count)s
        )
        ON DUPLICATE KEY UPDATE
            trades_closed = VALUES(trades_closed),
            wins = VALUES(wins),
            losses = VALUES(losses),
            win_rate = VALUES(win_rate),
            avg_realized_pnl_pct = VALUES(avg_realized_pnl_pct),
            avg_realized_pnl_eur = VALUES(avg_realized_pnl_eur),
            gross_profit_eur = VALUES(gross_profit_eur),
            gross_loss_eur = VALUES(gross_loss_eur),
            profit_factor = VALUES(profit_factor),
            avg_holding_minutes = VALUES(avg_holding_minutes),
            prepare_to_enter_count = VALUES(prepare_to_enter_count),
            prepare_fail_count = VALUES(prepare_fail_count)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, row)
            conn.commit()

    def insert_or_update_state_transition_daily(self, row: dict[str, Any]) -> None:
        sql = """
        INSERT INTO state_transition_daily (
            metric_date_utc,
            sleeve_code,
            strategy_name,
            from_state,
            to_state,
            transition_count,
            avg_forward_return_24h_pct,
            avg_forward_return_72h_pct
        ) VALUES (
            %(metric_date_utc)s,
            %(sleeve_code)s,
            %(strategy_name)s,
            %(from_state)s,
            %(to_state)s,
            %(transition_count)s,
            %(avg_forward_return_24h_pct)s,
            %(avg_forward_return_72h_pct)s
        )
        ON DUPLICATE KEY UPDATE
            transition_count = VALUES(transition_count),
            avg_forward_return_24h_pct = VALUES(avg_forward_return_24h_pct),
            avg_forward_return_72h_pct = VALUES(avg_forward_return_72h_pct)
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, row)
            conn.commit()
''',
    "src/synth_sleeves/metrics.py": r'''"""
SYNTH v2
Module: synth_sleeves.metrics
Purpose:
    Aggregate daily metrics from closed trade lots and transition events.
Boundary:
    - Pure computation helpers
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


DECIMAL_ZERO = Decimal("0")


def build_strategy_metrics_daily(trade_rows: list[dict], prepare_transition_rows: list[dict]) -> list[dict]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in trade_rows:
        key = (
            row["metric_date_utc"],
            row["sleeve_code"],
            row["strategy_name"],
            row.get("strategy_version_id"),
        )
        grouped[key].append(row)

    prep_counts: dict[tuple, dict[str, int]] = defaultdict(lambda: {"prepare_to_enter_count": 0, "prepare_fail_count": 0})
    for row in prepare_transition_rows:
        key = (
            row["metric_date_utc"],
            row["sleeve_code"],
            row["strategy_name"],
            row.get("strategy_version_id"),
        )
        if row["to_state"] == "ENTER_LONG":
            prep_counts[key]["prepare_to_enter_count"] += int(row["transition_count"])
        elif row["to_state"] in {"WATCH", "AVOID", "EXIT", "BLOCK"}:
            prep_counts[key]["prepare_fail_count"] += int(row["transition_count"])

    result: list[dict] = []
    for key, rows in grouped.items():
        metric_date_utc, sleeve_code, strategy_name, strategy_version_id = key
        trades_closed = len(rows)
        wins = sum(1 for row in rows if Decimal(str(row["realized_pnl_eur"])) > DECIMAL_ZERO)
        losses = sum(1 for row in rows if Decimal(str(row["realized_pnl_eur"])) <= DECIMAL_ZERO)
        gross_profit = sum((Decimal(str(row["realized_pnl_eur"])) for row in rows if Decimal(str(row["realized_pnl_eur"])) > DECIMAL_ZERO), start=DECIMAL_ZERO)
        gross_loss_abs = sum((abs(Decimal(str(row["realized_pnl_eur"]))) for row in rows if Decimal(str(row["realized_pnl_eur"])) <= DECIMAL_ZERO), start=DECIMAL_ZERO)
        avg_pnl_eur = sum((Decimal(str(row["realized_pnl_eur"])) for row in rows), start=DECIMAL_ZERO) / Decimal(trades_closed)
        avg_pnl_pct = sum((Decimal(str(row["realized_pnl_pct"])) for row in rows), start=DECIMAL_ZERO) / Decimal(trades_closed)
        avg_holding = sum((Decimal(str(row["holding_minutes"])) for row in rows), start=DECIMAL_ZERO) / Decimal(trades_closed)
        profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > DECIMAL_ZERO else Decimal("999999")

        prep = prep_counts[key]

        result.append(
            {
                "metric_date_utc": metric_date_utc,
                "sleeve_code": sleeve_code,
                "strategy_name": strategy_name,
                "strategy_version_id": strategy_version_id,
                "trades_closed": trades_closed,
                "wins": wins,
                "losses": losses,
                "win_rate": (Decimal(wins) / Decimal(trades_closed)) if trades_closed else DECIMAL_ZERO,
                "avg_realized_pnl_pct": avg_pnl_pct,
                "avg_realized_pnl_eur": avg_pnl_eur,
                "gross_profit_eur": gross_profit,
                "gross_loss_eur": gross_loss_abs,
                "profit_factor": profit_factor,
                "avg_holding_minutes": avg_holding,
                "prepare_to_enter_count": prep["prepare_to_enter_count"],
                "prepare_fail_count": prep["prepare_fail_count"],
            }
        )

    return result
''',
    "src/synth_sleeves/pipeline.py": r'''"""
SYNTH v2
Module: synth_sleeves.pipeline
Purpose:
    Example end-to-end sleeve + PREPARE + paper PnL loop.
Boundary:
    - Orchestrates already-existing upstream selection output
    - Does not fetch market data itself
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.synth_sleeves.agents import AGENT_REGISTRY
from src.synth_sleeves.allocator import allocate_targets
from src.synth_sleeves.config_loader import load_sleeve_config
from src.synth_sleeves.db_repository import SleeveRepository
from src.synth_sleeves.models import AgentSignalRow
from src.synth_sleeves.paper_pnl import build_fill_intents
from src.synth_sleeves.risk_policy import apply_risk_policy


def run_sleeve_pipeline_once(
    *,
    selection_rows: list[AgentSignalRow],
    wallet_equity_eur: Decimal,
    config_path: str,
    repository: SleeveRepository,
    min_trade_fraction: Decimal = Decimal("0.0050"),
) -> dict[str, int]:
    run_ts_utc = datetime.now(timezone.utc)
    sleeve_cfg = load_sleeve_config(config_path)

    proposals = []
    for row in selection_rows:
        for cfg in sleeve_cfg.values():
            for agent_name in cfg.agent_names:
                agent_fn = AGENT_REGISTRY[agent_name]
                proposal = agent_fn(run_ts_utc, row)
                if proposal is not None:
                    proposals.append(proposal)

    targets = allocate_targets(proposals, sleeve_cfg)
    risked_targets = apply_risk_policy(targets, sleeve_cfg)

    strategy_version_lookup = {}
    repository.insert_portfolio_targets(risked_targets, strategy_version_lookup)

    open_lots = repository.fetch_open_lots()
    intents = build_fill_intents(risked_targets, open_lots, min_trade_fraction=min_trade_fraction)

    return {
        "selection_rows": len(selection_rows),
        "proposals": len(proposals),
        "targets": len(risked_targets),
        "fill_intents": len(intents),
    }
''',
    "src/synth_sleeves/sql_metrics_queries.sql": r"""-- Closed trades for one UTC date
SELECT
    DATE(close_ts_utc) AS metric_date_utc,
    sleeve_code,
    strategy_name,
    strategy_version_id,
    realized_pnl_eur,
    realized_pnl_pct,
    holding_minutes
FROM trade_lot
WHERE DATE(close_ts_utc) = %s;

-- PREPARE transitions for one UTC date
SELECT
    DATE(created_ts_utc) AS metric_date_utc,
    sleeve_code,
    strategy_name,
    NULL AS strategy_version_id,
    from_state,
    to_state,
    transition_count
FROM state_transition_daily
WHERE metric_date_utc = %s
  AND from_state = 'PREPARE';
""",
    "scripts/recompute_strategy_metrics.py": r'''"""
SYNTH v2
Script: recompute_strategy_metrics
Purpose:
    Recompute daily sleeve/strategy metrics from trade_lot and state_transition_daily.
Usage:
    python -m scripts.recompute_strategy_metrics --date 2026-04-01
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from src.synth_sleeves.metrics import build_strategy_metrics_daily
from src.synth_sleeves.db_repository import SleeveRepository


def make_conn_params() -> dict[str, Any]:
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "database": os.environ["DB_NAME"],
    }


def fetch_rows(conn_params: dict[str, Any], sql: str, params: tuple[Any, ...]) -> list[dict]:
    with pymysql.connect(cursorclass=DictCursor, autocommit=True, charset="utf8mb4", **conn_params) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="UTC date in YYYY-MM-DD")
    args = parser.parse_args()

    metric_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    conn_params = make_conn_params()
    repo = SleeveRepository(conn_params)

    trade_sql = """
    SELECT
        DATE(close_ts_utc) AS metric_date_utc,
        sleeve_code,
        strategy_name,
        strategy_version_id,
        realized_pnl_eur,
        realized_pnl_pct,
        holding_minutes
    FROM trade_lot
    WHERE DATE(close_ts_utc) = %s
    """

    transition_sql = """
    SELECT
        metric_date_utc,
        sleeve_code,
        strategy_name,
        NULL AS strategy_version_id,
        from_state,
        to_state,
        transition_count
    FROM state_transition_daily
    WHERE metric_date_utc = %s
      AND from_state = 'PREPARE'
    """

    trade_rows = fetch_rows(conn_params, trade_sql, (metric_date,))
    transition_rows = fetch_rows(conn_params, transition_sql, (metric_date,))

    metrics = build_strategy_metrics_daily(trade_rows, transition_rows)
    for row in metrics:
        repo.insert_or_update_strategy_metrics_daily(row)

    print(f"[DONE] recomputed strategy metrics for {metric_date.isoformat()} rows={len(metrics)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "docs/integration_notes_synth_v2.md": r"""# Integration Notes — Sleeves + PREPARE + Paper PnL

## Existing pipeline
ETL -> feat -> signal -> advice -> selection -> decision -> risk -> portfolio -> execution

## Recommended updated pipeline
ETL -> feat -> signal -> advice -> selection
    -> sleeve_agents
    -> sleeve_allocator
    -> risk_policy
    -> portfolio_target
    -> execution_intent
    -> paper_lot_accounting
    -> position_snapshot / trade_lot / metrics

## Minimal v1 placement
You do not need to replace upstream modules yet.

Treat current `selection` output as the input to:
- `src/synth_sleeves.agents`
- `src/synth_sleeves.allocator`
- `src/synth_sleeves.risk_policy`

Then persist:
- `portfolio_target`

Then let a paper executor compare:
- current open sleeve lots
- new sleeve targets

And emit:
- OPEN
- ADD
- REDUCE
- CLOSE
- HOLD

## PREPARE policy
- CORE and SWING may emit PREPARE
- TACTICAL may not emit PREPARE
- PREPARE uses capped fraction and separate position count
- PREPARE must unwind if state degrades

## Immediate market response vs slow strategy review
- Immediate market response: every market loop
- Daily strategy metrics: once per UTC day
- Strategy logic changes: versioned, deliberate, not every minute
""",
    "example_usage/example_selection_to_sleeves.py": r"""from decimal import Decimal

from src.synth_sleeves.models import AgentSignalRow
from src.synth_sleeves.pipeline import run_sleeve_pipeline_once
from src.synth_sleeves.db_repository import SleeveRepository

selection_rows = [
    AgentSignalRow(
        asset_id=1,
        symbol="BTC-EUR",
        selection_state="PRE_ALIGNMENT",
        selection_score=Decimal("0.62"),
        selection_bias="WATCH",
        regime_ok=True,
        htf_reject=False,
        liquidity_ok=True,
        latest_price_eur=Decimal("61500"),
    ),
    AgentSignalRow(
        asset_id=2,
        symbol="PEPE-EUR",
        selection_state="TACTICAL",
        selection_score=Decimal("0.71"),
        selection_bias="TACTICAL",
        regime_ok=True,
        htf_reject=False,
        liquidity_ok=True,
        latest_price_eur=Decimal("0.00001234"),
    ),
    AgentSignalRow(
        asset_id=3,
        symbol="LDO-EUR",
        selection_state="LONG_READY",
        selection_score=Decimal("0.67"),
        selection_bias="LONG",
        regime_ok=True,
        htf_reject=False,
        liquidity_ok=True,
        latest_price_eur=Decimal("2.3500"),
    ),
]

repo = SleeveRepository(
    {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "synth",
        "password": "secret",
        "database": "synth",
    }
)

summary = run_sleeve_pipeline_once(
    selection_rows=selection_rows,
    wallet_equity_eur=Decimal("10000"),
    config_path="configs/portfolio_sleeves.yaml",
    repository=repo,
)

print(summary)
""",
    "IMPLEMENTATION_ORDER.txt": r"""1. Apply migration:
   database/migrations/0012_sleeves_prepare_pnl.sql

2. Add YAML:
   configs/portfolio_sleeves.yaml

3. Add Python modules:
   src/synth_sleeves/models.py
   src/synth_sleeves/config_loader.py
   src/synth_sleeves/strategy_versioning.py
   src/synth_sleeves/agents.py
   src/synth_sleeves/allocator.py
   src/synth_sleeves/risk_policy.py
   src/synth_sleeves/paper_pnl.py
   src/synth_sleeves/db_repository.py
   src/synth_sleeves/metrics.py
   src/synth_sleeves/pipeline.py

4. Connect current selection output to AgentSignalRow conversion.

5. Persist approved targets to portfolio_target.

6. Add paper execution loop:
   - fetch open lots
   - compare with targets
   - generate intents
   - update / close / snapshot lots

7. Add daily rollup:
   python -m scripts.recompute_strategy_metrics --date YYYY-MM-DD
""",
    "NEXT_PATCH_NOTES.txt": r"""Recommended immediate next patch after this bundle:

A. Add a real paper execution applier:
   - create lots on OPEN
   - create extra lots on ADD
   - reduce oldest lot first or weighted lot logic
   - close fully on CLOSE

B. Add transition logging:
   - WATCH -> PREPARE
   - PREPARE -> ENTER_LONG
   - PREPARE -> EXIT/WATCH/BLOCK

C. Add strategy_version writer:
   - hash YAML sub-config per strategy
   - insert active row automatically

D. Add a wallet_equity snapshot source:
   - equity = cash + market value of open lots

E. Add sleeve dashboards:
   - open lots by sleeve
   - realized/unrealized PnL by sleeve
   - PREPARE success rate by sleeve
""",
}


def main() -> int:
    root = Path.cwd()

    for rel_path, content in FILES.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        print(f"[WROTE] {rel_path}")

    print("[DONE] sleeves + PREPARE bundle files written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
