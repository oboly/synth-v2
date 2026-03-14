from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from synth.aplus.models import (
    APlusFactor,
    APlusRun,
    APlusSignal,
    ParsedAPlusAssetBlock,
    ParsedAPlusDocument,
)
from synth.common.enums import ConfidenceLabel, DirectionLabel, MagnitudeLabel, PhaseLabel
from synth.common.utc import ensure_utc


COIN_MAP: dict[str, str] = {
    "bitcoin": "BTC-EUR",
    "btc": "BTC-EUR",
    "ethereum": "ETH-EUR",
    "eth": "ETH-EUR",
    "xrp": "XRP-EUR",
    "solana": "SOL-EUR",
    "sol": "SOL-EUR",
    "polygon": "POL-EUR",
    "matic": "POL-EUR",
    "chainlink": "LINK-EUR",
    "link": "LINK-EUR",
    "avalanche": "AVAX-EUR",
    "avax": "AVAX-EUR",
    "cardano": "ADA-EUR",
    "ada": "ADA-EUR",
    "polkadot": "DOT-EUR",
    "dot": "DOT-EUR",
    "cosmos": "ATOM-EUR",
    "atom": "ATOM-EUR",
}


def _normalize_asset_code(label: str) -> str | None:
    key = label.strip().lower()
    return COIN_MAP.get(key)


def _extract_target_price(raw_block: str) -> Decimal | None:
    match = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]+)?)", raw_block)
    if not match:
        return None
    return Decimal(match.group(1).replace(",", ""))


def _extract_phase(raw_block: str) -> PhaseLabel | None:
    text = raw_block.lower()
    if "expansion" in text:
        return PhaseLabel.EXPANSION
    if "compression" in text:
        return PhaseLabel.COMPRESSION
    if "distribution" in text:
        return PhaseLabel.DISTRIBUTION
    return None


def parse_aplus_text(
    *,
    raw_text: str,
    created_ts: datetime,
    source_name: str = "chatgpt_a_plus",
    model_variant: str = "8.5D_breathline",
    prompt_label: str | None = None,
) -> ParsedAPlusDocument:
    """
    Parse a semi-structured A+ text dump into a normalized document.

    This is intentionally conservative:
    - If data is not present, leave it NULL/None.
    - Do not invent certainty.
    """
    created_ts = ensure_utc(created_ts)

    run = APlusRun(
        created_ts=created_ts,
        source_name=source_name,
        model_variant=model_variant,
        prompt_label=prompt_label,
    )

    assets: list[ParsedAPlusAssetBlock] = []

    # Split on lines that look like headings: "Bitcoin (BTC)" or "XRP"
    chunks = re.split(r"\n(?=[A-Z][A-Za-z0-9 ()/-]{1,40}\n)", raw_text.strip())

    for chunk in chunks:
        first_line = chunk.strip().splitlines()[0].strip() if chunk.strip() else ""
        if not first_line:
            continue

        asset_code = None

        # Try exact token in parens first
        symbol_match = re.search(r"\(([A-Za-z0-9]+)\)", first_line)
        if symbol_match:
            asset_code = _normalize_asset_code(symbol_match.group(1))

        if asset_code is None:
            asset_code = _normalize_asset_code(first_line)

        if asset_code is None:
            continue

        signal = APlusSignal(
            asset_code=asset_code,
            created_ts=created_ts,
            phase_label=_extract_phase(chunk),
            direction_label=DirectionLabel.BULLISH if "target" in chunk.lower() or "expected to reach" in chunk.lower() else None,
            magnitude_label=MagnitudeLabel.STRONG if "expansion" in chunk.lower() else None,
            confidence_label=None,
            confidence_score=None,
            horizon_label="unspecified",
            horizon_end_ts=None,
            target_price=_extract_target_price(chunk),
            target_currency="USD",
            raw_excerpt=chunk[:2000],
        )

        factors = [
            APlusFactor(
                factor_name="breathline_phase",
                factor_value_text=signal.phase_label.value if signal.phase_label else None,
            ),
        ]

        if signal.target_price is not None:
            factors.append(
                APlusFactor(
                    factor_name="symbolic_target_price",
                    factor_value_num=signal.target_price,
                    factor_unit=signal.target_currency,
                )
            )

        assets.append(
            ParsedAPlusAssetBlock(
                signal=signal,
                factors=factors,
                raw_block=chunk,
            )
        )

    return ParsedAPlusDocument(
        run=run,
        raw_text=raw_text,
        assets=assets,
    )
