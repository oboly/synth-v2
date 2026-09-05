"""Read-only regime evidence matrix composition for issue #617.

This module is deliberately downstream-only. It normalizes already-prepared
canonical market evidence into one inspectable read model without calculating
indicator truth, inventing thresholds, upgrading source status, or combining
components into a trade/regime score.

Architecture:
    canonical market evidence producers/contracts
    -> RegimeEvidenceCellV1
    -> RegimeEvidenceMatrixV1
    -> later reporting/dashboard renderer

The adapters below copy source-owned fields verbatim. Missing families may be
represented explicitly through ``unavailable_cell`` so the UI can show an
honest gap instead of silently omitting or fabricating evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

from src.features.eth_btc_leadership_snapshot_v1 import EthBtcLeadershipSnapshot
from src.features.evidence_contract_v1 import ObservedLifecycle, SignalHorizonV1Evidence
from src.features.ma_breadth_snapshot_v1 import MABreadthSnapshot
from src.features.momentum_evidence_snapshot_v1 import MomentumEvidenceSnapshot


FAMILY_BREADTH = "BREADTH"
FAMILY_ETH_BTC_LEADERSHIP = "ETH_BTC_LEADERSHIP"
FAMILY_MACRO_LIQUIDITY = "MACRO_LIQUIDITY"
FAMILY_MOMENTUM = "MOMENTUM"
FAMILY_VOLATILITY = "VOLATILITY"

COMPONENT_ETH_BTC_RAW = "RAW_COMPARISON"
COMPONENT_MA50_PARTICIPATION = "MA50_PARTICIPATION"
COMPONENT_MACD = "MACD"
COMPONENT_UNAVAILABLE = "UNAVAILABLE"

STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
REASON_NO_CANONICAL_OWNER = "NO_CANONICAL_OWNER"


@dataclass(frozen=True, slots=True)
class RegimeEvidenceCellV1:
    """One source-owned evidence component prepared for reporting.

    ``status`` and ``freshness`` are intentionally strings because upstream
    contracts do not all share one enum today. The matrix preserves those
    source values rather than translating AVAILABLE/FRESH/etc. into a new
    reporting-owned semantic state.

    ``scope_key`` is identity/provenance only. It distinguishes separate
    assets/universes whose upstream ``market`` field may be a generic label
    such as ``asset``. It never changes market semantics.

    ``observed_lifecycle`` preserves the upstream representation verbatim.
    `SignalHorizonV1Evidence` owns the structured `ObservedLifecycle`; the
    canonical MOMENTUM snapshot currently exposes only its lifecycle status
    string. The read model does not synthesize richer lifecycle evidence.
    """

    family: str
    component: str
    market: str
    scope_key: str
    status: str
    freshness: str | None
    asof_ts: datetime | None
    model_id: str | None
    model_version: str | None
    input_interval: str | None
    lookback_horizon: str | None
    effective_horizon: str | None
    observed_lifecycle: ObservedLifecycle | str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    provenance: dict[str, Any] = field(default_factory=dict)
    source_contract: str = ""

    @property
    def identity(self) -> tuple[str, str, str, str, str | None, str | None]:
        """Exact component identity for duplicate detection."""
        return (
            self.family,
            self.component,
            self.market,
            self.scope_key,
            self.input_interval,
            self.lookback_horizon,
        )

    @property
    def sort_key(self) -> tuple[str, str, str, str, str, str]:
        """Comparable deterministic ordering key.

        Optional identity fields stay optional in the canonical cell, but are
        mapped to an empty string only for sorting so Python never compares
        ``None`` directly with a string. Duplicate detection still uses the
        exact, unnormalized ``identity`` above.
        """
        return (
            self.family,
            self.component,
            self.market,
            self.scope_key,
            self.input_interval or "",
            self.lookback_horizon or "",
        )


@dataclass(frozen=True, slots=True)
class RegimeEvidenceMatrixV1:
    evaluated_at: datetime
    cells: tuple[RegimeEvidenceCellV1, ...]

    def by_family(self, family: str) -> tuple[RegimeEvidenceCellV1, ...]:
        return tuple(cell for cell in self.cells if cell.family == family)


def _signal_scope_key(evidence: SignalHorizonV1Evidence) -> str:
    """Build identity only from already-prepared provenance.

    SignalHorizonV1 adapters for Structure/Relative Strength/Rotation commonly
    use the generic ``market='asset'`` label. When venue/asset_id provenance is
    present, preserve it as the reporting identity key so multiple assets can
    coexist in one matrix. No symbol lookup or market inference occurs here.
    """
    venue = evidence.provenance.get("venue")
    asset_id = evidence.provenance.get("asset_id")
    if venue is not None or asset_id is not None:
        return f"venue={venue!s};asset_id={asset_id!s}"
    return evidence.market


def from_signal_horizon(evidence: SignalHorizonV1Evidence) -> RegimeEvidenceCellV1:
    """Copy an existing #243 SignalHorizonV1 evidence object verbatim."""
    return RegimeEvidenceCellV1(
        family=evidence.family,
        component=evidence.component,
        market=evidence.market,
        scope_key=_signal_scope_key(evidence),
        status=evidence.status,
        freshness=evidence.freshness,
        asof_ts=evidence.asof_ts,
        model_id=evidence.model_id,
        model_version=evidence.model_version,
        input_interval=evidence.input_interval,
        lookback_horizon=evidence.lookback_horizon,
        effective_horizon=evidence.effective_horizon,
        observed_lifecycle=evidence.observed_lifecycle,
        raw=dict(evidence.raw),
        reason_codes=tuple(evidence.reason_codes),
        provenance=dict(evidence.provenance),
        source_contract="SignalHorizonV1Evidence",
    )


def from_momentum(snapshot: MomentumEvidenceSnapshot) -> RegimeEvidenceCellV1:
    """Expose canonical raw MOMENTUM primitives without classifying them."""
    return RegimeEvidenceCellV1(
        family=FAMILY_MOMENTUM,
        component=COMPONENT_MACD,
        market=snapshot.market,
        scope_key=f"venue={snapshot.venue};asset_id={snapshot.asset_id};market={snapshot.market}",
        status=snapshot.status,
        freshness=snapshot.freshness,
        asof_ts=snapshot.asof_ts,
        model_id=snapshot.model_id,
        model_version=snapshot.model_version,
        input_interval=snapshot.input_interval,
        lookback_horizon=snapshot.lookback_horizon,
        effective_horizon=snapshot.effective_horizon,
        observed_lifecycle=snapshot.observed_lifecycle_status,
        raw={
            "data_quality": snapshot.data_quality,
            "fast_ema_period": snapshot.fast_ema_period,
            "slow_ema_period": snapshot.slow_ema_period,
            "signal_ema_period": snapshot.signal_ema_period,
            "macd_value": snapshot.macd_value,
            "signal_value": snapshot.signal_value,
            "histogram_value": snapshot.histogram_value,
            "histogram_delta": snapshot.histogram_delta,
        },
        reason_codes=tuple(snapshot.reason_codes),
        provenance=dict(snapshot.provenance),
        source_contract="MomentumEvidenceSnapshot",
    )


def from_ma_breadth(snapshot: MABreadthSnapshot) -> RegimeEvidenceCellV1:
    """Expose canonical MA breadth as-is; do not invent breadth bands."""
    return RegimeEvidenceCellV1(
        family=FAMILY_BREADTH,
        component=COMPONENT_MA50_PARTICIPATION,
        market=snapshot.universe_id,
        scope_key=f"venue={snapshot.venue};universe={snapshot.universe_id};hash={snapshot.universe_hash}",
        status=snapshot.data_status,
        freshness=snapshot.freshness_status,
        asof_ts=snapshot.asof_ts_utc,
        model_id=snapshot.model_id,
        model_version=snapshot.model_version,
        input_interval=snapshot.input_interval,
        lookback_horizon=snapshot.lookback_horizon,
        effective_horizon=snapshot.effective_horizon,
        raw={
            "eligible_count": snapshot.eligible_count,
            "evaluated_count": snapshot.evaluated_count,
            "insufficient_history_count": snapshot.insufficient_history_count,
            "stale_constituent_count": snapshot.stale_constituent_count,
            "coverage_pct": snapshot.coverage_pct,
            "universe_above_sma50_count": snapshot.universe_above_sma50_count,
            "universe_above_sma50_pct": snapshot.universe_above_sma50_pct,
        },
        provenance={
            "venue": snapshot.venue,
            "universe_id": snapshot.universe_id,
            "universe_version": snapshot.universe_version,
            "universe_hash": snapshot.universe_hash,
        },
        source_contract="MABreadthSnapshot",
    )


def from_eth_btc_leadership(snapshot: EthBtcLeadershipSnapshot) -> RegimeEvidenceCellV1:
    """Expose raw ETH/BTC comparison evidence; never infer a leader state."""
    market = f"{snapshot.eth_market} vs {snapshot.btc_market}"
    return RegimeEvidenceCellV1(
        family=FAMILY_ETH_BTC_LEADERSHIP,
        component=COMPONENT_ETH_BTC_RAW,
        market=market,
        scope_key=f"venue={snapshot.venue};{market}",
        status=snapshot.data_status,
        freshness=snapshot.freshness,
        asof_ts=snapshot.asof_ts_utc,
        model_id=snapshot.model_id,
        model_version=snapshot.model_version,
        input_interval=snapshot.input_interval,
        lookback_horizon=snapshot.lookback_horizon,
        effective_horizon=snapshot.effective_horizon,
        raw={
            "btc_return_pct": snapshot.btc_return_pct,
            "eth_return_pct": snapshot.eth_return_pct,
            "eth_minus_btc_return_pct": snapshot.eth_minus_btc_return_pct,
            "eth_btc_ratio_start": snapshot.eth_btc_ratio_start,
            "eth_btc_ratio_end": snapshot.eth_btc_ratio_end,
            "eth_btc_ratio_change_pct": snapshot.eth_btc_ratio_change_pct,
        },
        reason_codes=tuple(snapshot.reason_codes),
        provenance=dict(snapshot.provenance),
        source_contract="EthBtcLeadershipSnapshot",
    )


def unavailable_cell(*, family: str, detail: str | None = None) -> RegimeEvidenceCellV1:
    """Represent a known upstream ownership gap explicitly.

    This is repository/contract availability metadata, not a market state.
    It must never be interpreted as bearish/bullish evidence.
    """
    provenance: dict[str, Any] = {}
    if detail:
        provenance["detail"] = detail
    return RegimeEvidenceCellV1(
        family=family,
        component=COMPONENT_UNAVAILABLE,
        market="market",
        scope_key=f"unavailable:{family}",
        status=STATUS_INSUFFICIENT_DATA,
        freshness=None,
        asof_ts=None,
        model_id=None,
        model_version=None,
        input_interval=None,
        lookback_horizon=None,
        effective_horizon=None,
        observed_lifecycle=None,
        reason_codes=(REASON_NO_CANONICAL_OWNER,),
        provenance=provenance,
        source_contract="RegimeEvidenceMatrixV1.unavailable",
    )


def build_matrix(
    *,
    evaluated_at: datetime,
    cells: Iterable[RegimeEvidenceCellV1],
) -> RegimeEvidenceMatrixV1:
    """Build a deterministic matrix without aggregation or reinterpretation."""
    materialized = tuple(cells)
    identities = [cell.identity for cell in materialized]
    if len(identities) != len(set(identities)):
        duplicates = sorted(
            (identity for identity in set(identities) if identities.count(identity) > 1),
            key=lambda identity: tuple("" if value is None else str(value) for value in identity),
        )
        raise ValueError(f"duplicate regime evidence cell identities: {duplicates}")

    ordered = tuple(sorted(materialized, key=lambda cell: cell.sort_key))
    return RegimeEvidenceMatrixV1(evaluated_at=evaluated_at, cells=ordered)


def decimal_to_json_value(value: Any) -> Any:
    """Presentation helper for exact Decimal values without float coercion."""
    return str(value) if isinstance(value, Decimal) else value
