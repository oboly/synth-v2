# KITE Watchlist Candidate Check V1

## Purpose

Check whether KITE exists locally and whether local market data is sufficient for research-only watchlist monitoring.

## User Thesis

The user thesis is that KITE is Bitvavo-listed and may have attractive asymmetry. This document treats that as watchlist intake only.

## Boundary

This is not trading advice, not a buy/sell signal, and not runtime permission. No selection, advice, decision, execution, broker, order, or chain-script logic is changed by this report.

## Local Asset Metadata Findings

KITE is now present in local `asset` metadata as a disabled research/watchlist asset:

| Field | Value |
|---|---:|
| asset_id | 74 |
| symbol | KITE |
| name | Kite |
| quote_asset | EUR |
| asset_class | SMALL_ALT |
| is_enabled | 0 |
| is_tradeable | 0 |
| is_portfolio | 0 |

The disabled flags mean KITE is not promoted into the normal runtime universe.

## Candle Coverage Findings

Local `obs_market_candle` coverage exists for KITE on Bitvavo:

| Interval | Rows | First open UTC | Latest close UTC | Latest close |
|---|---:|---:|---:|---:|
| 1h | 3826 | 2025-11-18 11:00:00 | 2026-05-17 00:00:00 | 0.18463 |
| 4h | 1060 | 2025-11-18 08:00:00 | 2026-05-17 00:00:00 | 0.18463 |
| 1d | 180 | 2025-11-18 00:00:00 | 2026-05-17 00:00:00 | 0.18463 |

## Liquidity And Data Quality Notes

The recent 1h median `volume_quote_eur` is approximately 11.5k, below the conservative low-liquidity warning threshold used by this report. Recent 4h and 1d median quote-volume proxies are higher, but this should still be treated as a low-liquidity watchlist candidate until manually reviewed.

APT and SXT were also checked after the user clarified the watchlist scope:

| Symbol | Local metadata | Candle status | Note |
|---|---|---|---|
| APT | present, disabled | 1h/4h/1d present | research-only, not runtime enabled |
| KITE | present, disabled | 1h/4h/1d present | research-watchlist-ready |
| SXT | present, disabled | partial 4h coverage only | needs manual review |

ASX is not in scope because the user clarified it is not of interest.

## Recommendation

KITE is `RESEARCH_WATCHLIST_READY` for market-only monitoring. This means it can be reviewed as a watchlist candidate, not as a signal or order candidate.

## Next Step

Manually review `data/research/kite_watchlist_candidate_check_v1/kite_watchlist_candidate_check_v1.json`, then decide whether a separate follow-up should add research-only monitoring views for KITE, APT, and/or SXT.

## No Runtime Promotion

KITE remains disabled and non-tradeable in local metadata. Do not add KITE to runtime selection, advice, decision, execution, order, or chain scripts from this report.
