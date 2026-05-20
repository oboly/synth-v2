# Synth v2 — External PRO / RV / Macro Narrative Bundle

Generated: 2026-05-20
Purpose: save the usable summaries from the current collection chat into a repo-ready research bundle.
Destination suggestion: `docs/research/external_pro_narrative_registry.md`

## Storage policy

- Chat = intake / raw collection.
- Repo docs = durable storage.
- Assistant memory = do not use for ongoing PRO/RV dumps.
- Synth runtime = unchanged unless validated later.

## Architecture boundary

All entries are research-only external intelligence / narrative / thesis inputs.

Do not convert directly into:

- `selection_engine` scoring
- buy/sell signals
- `decision_gate` permissions
- `execution_planner` logic
- executor / broker writes / orders

Correct path:

```text
external note
→ external_pro_narrative_registry
→ normalized labels
→ watch-condition tracker
→ public-anchor / market-data validation
→ optional macro_context or feature proposal
→ only after testing: possible selection modifier or downstream constraint
```

---

# 1. Parent research lanes

## 1.1 Financial plumbing reset parent thesis

Core thesis:

```text
The reset is not announced as “reset”.
It arrives as compliance, messaging standards, identity rails, stablecoin rules,
tokenized securities, shipping documentation, custody rules, and jurisdictional access controls.
```

Suggested docs:

```text
docs/research/financial_plumbing_reset_watch_v1.md
docs/research/external_pro_narrative_registry.md
```

Suggested labels:

```text
FINANCIAL_PLUMBING_RESET
TOKENIZATION_OF_EVERYTHING
STABLECOIN_BANKING_INTEGRATION
ISO20022_TOKENIZED_VALUE_LAYER
TOKENIZED_SECURITIES_INFRA_ACCELERATION
DIGITAL_IDENTITY_ACCESS_LAYER
TRUST_OVER_IP_ACCESS_LAYER
JURISDICTIONAL_GEOFENCING
MARKET_SLEEP_WAKE_EVENT
```

High-priority watch signals:

```text
DTCC tokenization production timeline
CLARITY Act progress
GENIUS implementation
Nasdaq/NYSE/ICE tokenized securities notices
bank stablecoin/tokenized deposit launches
DTC/DTC tokenization notices
Trust over IP / digital ID rollouts
crypto access geofencing
market closures / Friday-to-Monday cutovers
```

## 1.2 Macro architecture reset 2026–2029

Core thesis:

```text
World events should be read as architecture, not isolated headlines:
sovereign debt, bond stress, energy, AI governance, digital ID, proxy conflict,
surveillance, and institutional tokenization are converging system layers.
```

Suggested labels:

```text
EXTERNAL_MACRO_ARCHITECTURE_RESET_2026_2029
HEMISPHERIC_CONTROL
MANAGED_CONFLICT_ECONOMY
SOVEREIGN_DEBT_LIQUIDITY_SHOCK
BOND_MARKET_FRACTURE
SURVEILLANCE_INFRA_PRIVATIZATION
AI_GOVERNANCE_FORMALIZATION
DIGITAL_MONETARY_RAILS_ACTIVATION
```

## 1.3 2032 inflection / access-management thesis

Core thesis:

```text
2032 is treated as a structural access boundary.
Before that boundary, capital, compliance, jurisdiction, BTC exposure,
AI/robotics adoption, and identity readiness determine whether an actor remains flexible
or becomes administratively managed.
```

Suggested labels:

```text
EXTERNAL_MACRO_ARCHITECTURE_2032_INFLECTION
BTC_STATELESS_SETTLEMENT_INFRA
TRUST_OVER_IP_IDENTITY_LAYER
AI_ROBOTICS_UPPER_K_POSITIONING
JURISDICTIONAL_OPTIONALITY
RESIDENCY_OVER_CITIZENSHIP
UBI_BINARY_GOVERNANCE_SIGNAL
COMPLIANCE_AS_ACCESS_CREDENTIAL
```

## 1.4 External algorithmic zone forecast lane

Martee’s Oracle should be stored separately from RV/A+/PRO narrative.

Suggested doc:

```text
docs/research/external_algorithmic_zone_forecast_v1.md
```

Suggested schema:

```text
source_model: MARTEE_ORACLE
asset_class: CRYPTO / EQUITY_INDEX / FX / COMMODITY
asset: string
zone_low: decimal
zone_high: decimal
time_window: string
ta_alignment: TRUE / FALSE
oracle_alignment: TRUE / FALSE
reaction_expected: SUPPORT / RESISTANCE / BREAKOUT / CHECKBACK
validation_status: PENDING / HIT_REACTED / HIT_FAILED / NEVER_HIT
market_response_score: 0_to_5
```

## 1.5 Event-window validation lane

Use for RV sessions with concrete time windows.

Suggested docs/data:

```text
docs/research/macro_watch_windows_v1.md
data/research/external_watch_windows/
```

Suggested scoring:

```text
target_match_score
delta_match_score
timing_score
market_response_score
false_positive_notes
usable_feature_candidate
```

---

# 2. Registry index — processed entries

## 2.1 BTC B-wave / alt rotation thesis

Key summary:

```text
BTC reaching the 0.618 retracement around ~$100K plus volume-confirmed B-wave exhaustion
is the conditional trigger for alt rotation.
Until confirmed, sideways alt action is pre-rotation accumulation/watchlist context,
not exit logic.
```

Labels:

```text
BTC_B_WAVE_ALT_ROTATION
CONDITIONAL_MACRO_ROTATION
BTC_0618_RETRACEMENT_VOLUME_CONFIRMED_TOP
ALT_ROTATION_PRECONDITION
```

## 2.2 Institutional counterparty assets

Assets:

```text
HBAR
Yellow
Canton / DTCC-type infrastructure
```

Key summary:

```text
Institutional-counterparty assets have a different risk profile from speculative tokens.
Canton/DTCC ceiling scenarios should reference DTCC settlement-volume context,
not only current market cap.
```

Labels:

```text
INSTITUTIONAL_SETTLEMENT_INFRA
COUNTERPARTY_NETWORK_OPTIONALITY
SETTLEMENT_VOLUME_CEILING_CONTEXT
```

## 2.3 Meme liquidity realism rule

Key summary:

```text
A pump is irrelevant if the exit liquidity is not real.
Before entry, ask: where is liquidity deep enough to exit at the pump price?
```

Labels:

```text
EXIT_LIQUIDITY_FRAGILITY
REALIZABLE_EXIT_QUALITY
PUMP_QUALITY_AFTER_SLIPPAGE
```

## 2.4 Bitcoin miners pivoting to AI/HPC

Key summary:

```text
BTC miners do not generally create their own tradeable AI tokens.
The pivot is BTC mining infrastructure → AI/HPC compute/data-center/power infrastructure.
```

Equity names discussed:

```text
IREN
Hut 8
Core Scientific
Cango
```

Crypto-proxy basket:

```text
BTC
RENDER
TAO
AKT
FIL
```

Labels:

```text
AI_INFRA_MINER_PIVOT_PROXY
POWER_GRID_DATACENTER_COMPUTE_BOTTLENECK
```

## 2.5 Tokenized securities / Trump Monday cutover claim

Key summary:

```text
The rails are real; the full-market Monday cutover is not confirmed.
Best phrasing: regulated tokenized securities infrastructure is activating/accelerating.
```

Labels:

```text
MONDAY_TOKENIZED_SECURITIES_CUTOVER
PLAUSIBLE_SUBSET_BUT_UNCONFIRMED
TOKENIZED_SECURITIES_INFRA_ACCELERATION
NASDAQ_TOKENIZED_SECURITIES_ACTIVATION
NYSE_ICE_24_7_TOKENIZED_SECURITIES_PLATFORM
```

Impacted token watch:

```text
Tier 1: ONDO, LINK, CC/Canton, AVAX, ETH, SOL
Tier 2: POL, XDC, HBAR, XRP, XLM, MKR/SKY, CFG, MPL/SYRUP
Macro overlap: BTC, PAXG, XAUT
```

## 2.6 Lightning / Bitcoin open rails

Key summary:

```text
Lightning is not a coin.
Bitcoin is the asset.
Lightning, Taproot Assets, and RGB are open Bitcoin rails/protocol layers.
```

Labels:

```text
OPEN_BITCOIN_SETTLEMENT_RAILS
LIGHTNING_NETWORK_NOT_A_TOKEN
TAPROOT_ASSETS_PROTOCOL
RGB_PROTOCOL
BTC_AS_OPEN_SETTLEMENT_ASSET
```

## 2.7 FFGRV macro architecture reset — May 10

Key summary:

```text
Americas as strategic zone, proxy conflict as managed conflict economy,
US-China coordinated friction thesis, 2026–2029 reset window,
hantavirus/surveillance watch conditions, and surveillance privatization.
```

Labels:

```text
EXTERNAL_MACRO_ARCHITECTURE_RESET_2026_2029
HEMISPHERIC_CONTROL
MANAGED_CONFLICT_ECONOMY
US_CHINA_COORDINATED_FRICTION_THESIS
PANDEMIC_READINESS_SIGNAL
SURVEILLANCE_INFRA_PRIVATIZATION
```

## 2.8 Founders Call with Jonas — 2032 inflection

Key summary:

```text
Capital, jurisdiction, BTC, AI/robotics adoption, digital identity, compliance clarity,
UBI, and Trust over IP are framed as the key positioning variables before 2032.
```

Labels:

```text
EXTERNAL_MACRO_ARCHITECTURE_2032_INFLECTION
BTC_STATELESS_SETTLEMENT_INFRA
TRUST_OVER_IP_IDENTITY_LAYER
AI_ROBOTICS_UPPER_K_POSITIONING
JURISDICTIONAL_OPTIONALITY
UBI_BINARY_GOVERNANCE_SIGNAL
```

## 2.9 RV bond market fracture

Key summary:

```text
Late-2026 to early-2027 sovereign bond/liquidity fracture window.
Dimon warning treated as public recognition phase, not origin of signal.
```

Labels:

```text
EXTERNAL_RV_BOND_MARKET_FRACTURE
SOVEREIGN_DEBT_LIQUIDITY_SHOCK
LATE_2026_EARLY_2027_INFLECTION
PAPER_CLAIMS_REPRICING
DIGITAL_MONETARY_RAILS_ACTIVATION
G7_DURATION_STRESS
```

## 2.10 AI / policy / July inflection post-debrief

Key summary:

```text
July 4–7 2026 is treated as a synchronization window:
AI governance, crypto regulation, Fed tone, U.S.–China alignment, energy/geopolitics.
```

Labels:

```text
MID_2026_SYNCHRONIZATION_WINDOW
AI_GOVERNANCE_FORMALIZATION
US_CRYPTO_REGULATORY_CLARITY_ACCELERATION
CLARITY_ACT_POLICY_WINDOW
FED_CRYPTO_POLICY_TONE_SHIFT
COORDINATION_BEFORE_ENFORCEMENT_SEQUENCE
```

## 2.11 RV UN AI Geneva July 2026

Key summary:

```text
Known event: UN Global Dialogue on AI Governance, Geneva, July 6–7 2026.
RV overlay: possible military/security, financial, cyber/viral, public-order deltas.
```

Labels:

```text
EXTERNAL_RV_UN_AI_GENEVA_JULY_2026
JULY_2026_AI_GOVERNANCE_WINDOW
AI_GOVERNANCE_HARDENING
AI_MILITARY_GOVERNANCE_ESCALATION
AI_FINANCIAL_SYSTEM_STRESS_LINK
VIRAL_VECTOR_AMBIGUITY_CLUSTER
PUBLIC_RESPONSE_TO_STRUCTURAL_SHIFT
```

## 2.12 Shenzhen financial reset review

Key summary:

```text
Stablecoin regulation, ISO 20022, tariff/de-minimis restructuring,
crypto geofencing, Trust over IP, and jurisdictional compliance are interpreted
as coordinated financial plumbing preparation.
```

Labels:

```text
EXTERNAL_RV_SHENZHEN_FINANCIAL_RESET
FINANCIAL_PLUMBING_RESET
ISO20022_TOKENIZED_VALUE_LAYER
STABLECOIN_BANKING_INTEGRATION
CRYPTO_ACCESS_GEOFENCING
INFORMATION_GEOFENCING
MARKET_SLEEP_WAKE_EVENT
SHOCKER_AS_RESET_COVER
```

## 2.13 Martee Weekly Update — May 18

Key summary:

```text
Cross-asset regime map:
DXY bear flag, Nasdaq exhaustion/checkback, BTC buy signal forming but $88K not reclaimed,
HYPE relative strength, LINK/NEAR/XRP/XLM still BTC-correlated,
oil trend extension, cotton Oracle+TA confluence, natgas bottom breakout.
```

Labels:

```text
EXTERNAL_MARTEE_WEEKLY_UPDATE
MARTEE_ORACLE_ZONE_MODEL
CROSS_ASSET_MACRO_TA_CONTEXT
DXY_BEAR_FLAG_CONTINUATION_WATCH
BTC_88000_RECLAIM_BUY_SIGNAL_WATCH
HYPE_RELATIVE_STRENGTH_LEADER
LINK_MARKET_CONFIRMATION_PENDING
COTTON_ORACLE_TA_CONFLUENCE
NATGAS_WINTER_SUPPLY_BREAKOUT
```

## 2.14 King’s Speech decoded — UK reset

Key summary:

```text
UK shift from efficiency-market governance to resilience-state governance:
steel, digital ID, cyber resilience, Northern Powerhouse Rail, defence/energy security,
ToIP/2032 access-management trajectory.
```

Labels:

```text
FFGRV_KINGS_SPEECH_UK_RESET_2026
UK_STRATEGIC_RESILIENCE_SHIFT
UK_STEEL_DEFENSE_INDUSTRIAL_SIGNAL
UK_DIGITAL_ID_ACCESS_LAYER
CYBER_ID_SECURITY_CONVERGENCE
NORTHERN_ENGLAND_INFRASTRUCTURE_RESHAPING
TOIP_2032_ACCESS_MANAGEMENT_TRAJECTORY
```

## 2.15 May 2026 RV world events

Key summary:

```text
May 2026 stress-window: AI-vs-AI, AI-guided weapons, grid outage, financial cyberattack,
oil/Hormuz risk, money-supply expansion, volatile markets, selected crypto charts.
```

Assets:

```text
BTC
TAO
RENDER
HBAR
CVX
USO/oil
```

Labels:

```text
EXTERNAL_RV_MAY_2026_WORLD_EVENTS
AI_MODEL_COMPETITION_ESCALATION
AI_GUIDED_WEAPON_INFRASTRUCTURE_RISK
GRID_DARK_OUTAGE_WATCH
FINANCIAL_INFRA_CYBERATTACK_WATCH
HORMUZ_REFINERY_OIL_SHOCK_WATCH
MONEY_SUPPLY_EXPANSION_SIGNAL
```

## 2.16 RV Chainlink 2026–2028

Key summary:

```text
RV convergence around infrastructure, transport chains, boardrooms, resource extraction,
settlement layers, and upward charts maps strongly to Chainlink’s public RWA/oracle/CCIP thesis.
```

Labels:

```text
EXTERNAL_RV_CHAINLINK_LINK_2026_2028
CHAINLINK_AS_TOKENIZED_ASSET_MIDDLEWARE
CHAINLINK_CCIP_INSTITUTIONAL_STANDARD
DTCC_CHAINLINK_COLLATERAL_APPCHAIN
TOKENIZED_COMMODITIES_ORACLE_LAYER
LINK_RELATIVE_STRENGTH_CONFIRMATION
LINK_VALUE_CAPTURE_DIVERGENCE
```

Status:

```text
LINK = thesis strong, market confirmation pending
```

## 2.17 LINK / HYPE / DOGE asset vetting

Key summary:

```text
LINK = strategic infrastructure, indirect value-capture.
HYPE = direct revenue/buyback value-capture.
DOGE = cultural meme/liquidity spike trade.
```

Labels:

```text
LINK_INFRA_STRONG_VALUE_CAPTURE_INDIRECT
HYPE_DIRECT_VALUE_CAPTURE_REVENUE_BUYBACK
DOGE_MEME_SPIKE_TRADE
EARLY_Q2_ALT_ROTATION
UNDERWRITABLE_CASHFLOW_TOKEN_PREFERENCE
```

## 2.18 ENJ / AERO / ALGO

Key summary:

```text
ENJ = speculative gaming/NFT revival lottery ticket.
AERO = structural Base/DeFi liquidity hub thesis with lock/supply strength.
ALGO = long-duration quantum-safe / RWA settlement thesis.
```

Labels:

```text
ENJ_GAMING_NFT_REVIVAL_SPECULATIVE
AERO_BASE_DEFI_LIQUIDITY_HUB
ALGO_QUANTUM_SAFE_INFRA_LONG_DURATION
```

Near-term ENJ watch:

```text
EUR 0.050–0.055 reclaim with volume = better rotation confirmation
EUR <0.034 = likely pump-fade/distribution risk
USD 0.31 = larger structural confirmation threshold
```

## 2.19 ADA / SOL / SUI asset vetting

Key summary:

```text
ADA = mature governance/protocol asset, lower convexity.
SUI = competitive growth L1, high convexity.
SOL = institutional high-throughput rail, reliability/restart risk.
```

Labels:

```text
ADA_MATURE_GOVERNANCE_ASSET_LOW_CONVEXITY
SUI_COMPETITIVE_GROWTH_L1_HIGH_CONVEXITY
SOL_INSTITUTIONAL_HIGH_THROUGHPUT_TROJAN_HORSE
L1_EXECUTION_PLATFORM_COMPARISON
PRODUCTIVE_PROTOCOL_CAPITAL
```

## 2.20 XRP / HBAR / Yellow / IO.net

Key summary:

```text
XRP = established settlement rail, value-capture question.
HBAR = institutional long-game technology play.
Yellow = early crypto-clearing / DTCC-like microcap.
IO.net = high-risk distributed GPU/AI compute; TAO is quality benchmark.
```

Labels:

```text
XRP_SETTLEMENT_INFRA_VALUE_CAPTURE_QUESTION
HBAR_INSTITUTIONAL_LONG_GAME_TECHNOLOGY_PLAY
YELLOW_CRYPTO_DTCC_MICROCAP_CLEARING_INFRA
IONET_HIGH_RISK_AI_COMPUTE_DEPIN_WATCH
TAO_AS_HIGHER_QUALITY_AI_INFRA_COMPARISON
```

## 2.21 Paper Bills → Blockchain

Key summary:

```text
Crypto adoption = digitization of value administration:
identity, property, vehicles, commodities, energy, settlement, and compliance.
```

Labels:

```text
GLOBAL_VALUE_ADMINISTRATION_LAYER
TOKENIZATION_OF_EVERYTHING
DIGITAL_IDENTITY_FOUNDATION
HIGH_TPS_VALUE_ADMIN_RAILS
CHAINLINK_REAL_WORLD_DATA_PACKAGING_LAYER
BITCOIN_GENERATIONAL_WEALTH_ASSET
ALTCOIN_ESCALATOR_MODEL
AI_ACCELERATED_TOKENIZATION_BUILDOUT
ENERGY_TOKENIZATION_FRONTIER
```

## 2.22 ISO 20022 / regulated future basket

Precision:

```text
ISO 20022 is a messaging standard, not a token certification.
Use ISO20022_ALIGNED / COMPLIANCE_RAILS_NARRATIVE.
```

Assets:

```text
XRP
XLM
ADA
HBAR
IOTA
QNT
ALGO
XDC
```

Labels:

```text
EXTERNAL_PRO_ISO20022_REGULATED_CRYPTO_BASKET
COMPLIANCE_IS_COMPETITIVE_EDGE
ISO20022_ALIGNED_CRYPTO_NARRATIVE
XDC_TRADE_FINANCE_COMPLIANCE_UNDERDOG
QNT_INTEROPERABILITY_OVERLEDGER_RAIL
HBAR_ENTERPRISE_HIGH_SPEED_SETTLEMENT_RAIL
```

## 2.23 RED / Kite / SENT

Key summary:

```text
RED = modular RWA oracle / Canton-adjacent high-beta challenger.
Kite = AI-agent payments / agentic commerce.
SENT = open-AGI monetization moonshot.
```

Labels:

```text
AI_BLOCKCHAIN_CONVERGENCE
RED_MODULAR_RWA_ORACLE_CANTON_ADJACENT
RED_STM_RWA_DATA_MONETIZATION
KITE_AGENTIC_AI_PAYMENTS_INFRA
KITE_AGENT_PASSPORT_IDENTITY_LAYER
SENT_OPEN_AGI_ECONOMY_HIGH_RISK
AI_TOKEN_HYPE_OVEREXTENSION
```

## 2.24 Canton / QNT / Worldcoin drawdown entry

Key summary:

```text
CC = institutional privacy rail.
QNT = interoperability / tokenized-deposit operating layer.
WLD = human/AI identity gate.
```

Labels:

```text
CANTON_PRIVACY_PRESERVING_INSTITUTIONAL_L1
DTCC_TOKENIZED_TREASURY_RAIL
QNT_OVERLEDGER_INTEROPERABILITY_RAIL
TOKENIZED_DEPOSITS_CBDC_INFRA
WORLDCOIN_PROOF_OF_PERSONHOOD_LAYER
AI_HUMAN_VERIFICATION
UBI_WORK_ALLOCATION_IDENTITY_INFRA
```

## 2.25 Janis BTC solar/lunar cycles / 2027 nexus

Key summary:

```text
Lunar cycles = potential correction/cooling windows.
Solar cycles = potential uptrend windows.
Next solar cycle window: 2026-08-12 through 2029-12-31.
2027–2028 framed as a nexus point.
```

Labels:

```text
BTC_SOLAR_LUNAR_CYCLE_OVERLAY
LUNAR_CORRECTION_PHASE_THESIS
SOLAR_UPTREND_PHASE_THESIS
BTC_NEW_SOLAR_CYCLE_2026_08_12_TO_2029_12_31
2027_2028_NEXUS_POINT
```

Validation idea:

```text
For each total lunar/solar eclipse:
  measure BTC returns -8w to +8w
  compare with random-date baseline
  test volatility/drawdown/trend-change frequency
```

## 2.26 Eugeni legal identity / energy architecture

Key summary:

```text
Legal identity, birth certificates, jurisdictional accounting, ecclesial identity risk,
breakthrough-energy thesis, Type-1 civilization energy window, 2032–2036 population stress.
```

Labels:

```text
LEGAL_IDENTITY_AS_JURISDICTIONAL_ACCOUNT
BIRTH_CERTIFICATE_ACCOUNTING_THESIS
ECCLESIAL_IDENTITY_OBLIGATION_RISK
BREAKTHROUGH_ENERGY_SUPPRESSION_THESIS
TYPE1_CIVILIZATION_ENERGY_WINDOW
POPULATION_REPLACEMENT_2032_2036
```

Status:

```text
Medium Synth relevance.
Macro/identity/energy context only.
No direct market signal.
```

## 2.27 Chad ancient builders / galactic cycles / AI career pivot

Key summary:

```text
Low market relevance, high personal/business relevance:
AI-future-viable business pivot, prompt quality as bottleneck, small-team AI acceleration,
cold-approach businesses for AI integration, gratitude as strategic infrastructure.
```

Labels:

```text
AI_FUTURE_VIABLE_BUSINESS_PIVOT
PROMPT_QUALITY_AS_AI_BOTTLENECK
SMALL_TEAM_AI_ACCELERATION
AI_CONSULTING_LOCAL_BUSINESS_OPPORTUNITY
GRATITUDE_AS_STRATEGIC_INFRASTRUCTURE
```

Destination:

```text
External registry as low-priority context
or separate personal/business strategy doc
```

---

# 3. Astro / celestial module status

Prior context indicates an older Astro & World Events Integration Pack existed before current Synth v2 work:

```text
events_loader.py
astro_score.py
risk_gate.py
calendar CSV for eclipses/Saturn stations/FOMC
SQL DDL + views
AstroScorer.score_at(now, events)
RiskGate.apply(score)
```

Known prior concept:

```text
astro window flag
eclipse windows ±5 days
planetary regime flags: Jupiter / Saturn
event risk regime module
```

Current confidence:

```text
Synth v1 / older TOS-era astro pack: likely existed as design/stub bundle
Synth v2 committed runtime module: not confirmed from this chat
```

Repo verification command:

```bash
cd ~/projects/synth-v2

echo "--- astro/celestial file search ---"
find . -path './.git' -prune -o -type f \
  \( -iname '*astro*' -o -iname '*celestial*' -o -iname '*eclipse*' -o -iname '*lunar*' -o -iname '*solar*' \) \
  -print | sort

echo
echo "--- content grep ---"
grep -RInE "astro|celestial|eclipse|lunar|solar|planetary|Jupiter|Saturn|FOMC|RiskGate|AstroScorer" \
  docs src scripts db 2>/dev/null | head -200
```

If no v2 module exists, suggested v2 research lane name:

```text
btc_celestial_cycle_overlay_v1
```

Strict boundary:

```text
research-only
market-only
no selection_engine changes
no decision_gate changes
no execution logic
```

---

# 4. Proposed repo files

Immediate save target:

```text
docs/research/external_pro_narrative_registry.md
```

Follow-up docs:

```text
docs/research/financial_plumbing_reset_watch_v1.md
docs/research/external_algorithmic_zone_forecast_v1.md
docs/research/macro_watch_windows_v1.md
docs/research/asset_vetting_external_registry_v1.md
docs/research/btc_celestial_cycle_overlay_v1.md
```

Optional data dirs later:

```text
data/research/external_pro_registry/
data/research/external_watch_windows/
data/research/external_asset_vetting/
data/research/external_oracle_zones/
```

---

# 5. Priority queue

## Highest Synth relevance

```text
financial plumbing reset parent thesis
DTCC / tokenized securities timeline
LINK / Chainlink RV + DTCC AppChain
ONDO / CC / Canton / RED / QNT / XDC / HBAR
Martee Oracle external zone model
BTC B-wave alt rotation condition
July 2026 UN AI governance watch window
Bond market fracture / duration stress
BTC celestial cycle overlay
```

## Medium relevance

```text
AI-blockchain infrastructure basket: RED / Kite / SENT
XRP / HBAR / Yellow / IO.net
ADA / SOL / SUI
Canton / QNT / Worldcoin
UK King’s Speech digital ID / resilience-state shift
Eugeni legal identity / energy architecture
```

## Lower market relevance / keep out of trading trackers

```text
Chad ancient builders / galactic cycle / gratitude
hidden tech / ET / metaphysical material unless tied to energy/identity macro context
```

---

# 6. Implementation discipline

This bundle should not change runtime behavior.

Recommended commit message if saved directly:

```text
Add external PRO narrative registry bundle
```

Recommended branch:

```text
research/external-pro-narrative-registry-v1
```

Smoke check after saving:

```bash
cd ~/projects/synth-v2

git status --short
test -f docs/research/external_pro_narrative_registry.md && echo "[OK] registry doc exists"
grep -n "FINANCIAL_PLUMBING_RESET" docs/research/external_pro_narrative_registry.md | head
grep -n "CHAINLINK_AS_TOKENIZED_ASSET_MIDDLEWARE" docs/research/external_pro_narrative_registry.md | head
grep -n "BTC_SOLAR_LUNAR_CYCLE_OVERLAY" docs/research/external_pro_narrative_registry.md | head
```
