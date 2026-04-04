"""
SYNTH v2
Module: synth_sleeves.pipeline
Purpose:
    End-to-end sleeve + PREPARE + paper PnL loop with state-aware Patch 3.2 execution.
Boundary:
    - Orchestrates upstream selection output
    - Does not fetch market data itself
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from src.synth_sleeves.agents import AGENT_REGISTRY
from src.synth_sleeves.allocator import allocate_targets
from src.synth_sleeves.config_loader import load_sleeve_config, load_sleeve_config_raw
from src.synth_sleeves.db_repository import SleeveRepository
from src.synth_sleeves.equity import compute_wallet_equity_eur
from src.synth_sleeves.models import AgentSignalRow
from src.synth_sleeves.paper_execution import PaperExecutionApplier
from src.synth_sleeves.risk_policy import apply_risk_policy
from src.synth_sleeves.transition_logger import build_transition_rows
from src.synth_sleeves.version_repo import StrategyVersionRepository


def run_sleeve_pipeline_once(
    *,
    selection_rows: list[AgentSignalRow],
    paper_cash_eur: Decimal,
    config_path: str,
    repository: SleeveRepository,
    min_trade_fraction: Decimal = Decimal("0.0050"),
    snapshot_every_loop: bool = True,
) -> dict[str, int | str]:
    run_ts_utc = datetime.utcnow()

    sleeve_cfg = load_sleeve_config(config_path)
    sleeve_cfg_raw = load_sleeve_config_raw(config_path)

    version_repo = StrategyVersionRepository(repository._connection_params)
    strategy_version_lookup = version_repo.build_lookup_from_sleeve_config(
        sleeve_config_raw=sleeve_cfg_raw
    )

    repository.close_zero_quantity_open_lots(run_ts_utc)
    open_lots_before = repository.fetch_open_lots()

    wallet_equity_eur = compute_wallet_equity_eur(
        paper_cash_eur=paper_cash_eur,
        open_lots=open_lots_before,
    )

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
    repository.insert_portfolio_targets(risked_targets, strategy_version_lookup)

    transition_rows = build_transition_rows(
        run_ts_utc=run_ts_utc,
        targets=risked_targets,
        open_lots=open_lots_before,
    )
    for row in transition_rows:
        repository.insert_or_update_state_transition_daily(row)

    applier = PaperExecutionApplier(repository)
    execution_summary = applier.apply(
        run_ts_utc=run_ts_utc,
        targets=risked_targets,
        open_lots=open_lots_before,
        wallet_equity_eur=wallet_equity_eur,
        min_trade_fraction=min_trade_fraction,
        snapshot_every_loop=snapshot_every_loop,
    )

    return {
        "run_ts_utc": run_ts_utc.isoformat(),
        "selection_rows": len(selection_rows),
        "proposals": len(proposals),
        "targets": len(risked_targets),
        "transitions": len(transition_rows),
        **execution_summary,
    }
