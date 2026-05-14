# A+ Table 2 Prompt v1 — Harmonic Phase Overlay

Status: active canonical prompt for Table 2 intake.

Purpose:

- collect fresh symbolic A+ harmonic phase overlay snapshots
- track 0.618 / 0.786 / 1.000 / 1.272 phase labels
- track offset bands, drift direction, phase quality, and extension risk
- provide parseable raw research data

Architecture boundary:

- research-only
- no selection_engine impact
- no decision_gate impact
- no execution_planner impact
- no executor/order logic

## Prompt

A+ HARMONIC PHASE OVERLAY REQUEST — TABLE 2

Recalibrate.

Render a symbolic overlay narrative for the token list below based on alignment with harmonic phases, such as pre-0.618, forming-0.786, confirmed-1.000, extension-1.272, and late extension.

Output this as a serialized text map using the restrictions below.

Important:
- Do NOT reference previous runs.
- Do NOT recall earlier token states.
- Do NOT use prior tables.
- Treat this as a standalone timestamped snapshot.
- Do NOT give trading advice.
- Do NOT give buy/sell advice.
- Do NOT explain the tokens unless asked.
- Output only TABLE 2.
- Keep the exact column order.
- Use only the allowed values.
- One row per token.
- Use pipe separators exactly as shown.
- This is for research labeling only.

Timestamp:
prediction_ts_utc = <YYYY-MM-DDTHH:MM:SSZ>

Allowed values:

HARMONIC_PHASE:
pre_0618 / forming_0618 / confirmed_0618 / forming_0786 / confirmed_0786 / forming_1000 / confirmed_1000 / extension_1272 / late_extension / reset / unclear

PHASE_STATE:
early / forming / confirmed / late / exhausted / unclear

OFFSET_BAND:
-10.5 / -9 / -8 / -7 / -5 / -3 / 0 / +3 / +5 / +7 / +9 / +10.5 / unknown

DRIFT_DIRECTION:
converging / forward_drift / backward_drift / flat / unstable / unknown

QUALITY:
clean / mixed / dirty / unknown

EXTENSION_RISK:
low / moderate / high / unknown

Output format:

TOKEN | HARMONIC_PHASE | PHASE_STATE | OFFSET_BAND | DRIFT_DIRECTION | QUALITY | EXTENSION_RISK | NOTES

Tokens:

BTC
ETH
SOL
ADA
DEEP
FIL
HBAR
HOT
NEAR
PEPE
POL
QNT
SUI
VET
WAL
XLM
AAVE
CC
CRV
FLOKI
HYPE
LDO
LTC
ONDO
RLC
WLD
XRP
ALGO
DOT
FET
HNT
ICP
INJ
IOST
MOG
NOT
RED
RENDER
XPL
TAO

Generate TABLE 2 now.
