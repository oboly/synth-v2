from decimal import Decimal

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
