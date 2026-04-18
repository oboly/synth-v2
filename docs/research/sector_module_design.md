SYNTH SECTOR MODULE – ONTWERP SAMENVATTING
==========================================

DOEL
----
De sector module voegt een extra analyzelaag toe aan de Synth trading bot.
Naast individuele coin-signalen kan het systeem hiermee:

- sector momentum meten
- sector rotaties detecteren
- narratives herkennen
- asset ranking verbeteren met marktcontext

Voorbeeld:
RENDER stijgt + sector AI stijgt → sterk signaal
RENDER stijgt + sector AI zwak → zwakker signaal


ALGEMENE ARCHITECTUUR
---------------------

De sectoranalyse wordt opgebouwd in vier stappen:

asset signals
      ↓
asset → sector mapping
      ↓
sector snapshots
      ↓
sector regime interpretatie

Of:

asset data → sector metrics → sector regime → trading signals


DATABASE ONTWERP
----------------

1. sector
---------
Definitie van sectoren.

Voorbeelden:

AI
DEFI
L1
NFT
MEME
DATA
DEX
PERPS
BTC_ECOSYSTEM

Velden:

sector_id
sector_code
sector_name
created_at


2. asset_sector_map
-------------------

Koppelt assets (coins) aan sectoren.

Many-to-many structuur omdat een coin meerdere sectoren kan hebben.

Voorbeelden:

RENDER → AI (0.7)
RENDER → DATA (0.3)

HYPE → PERPS (0.6)
HYPE → DEX (0.4)

Velden:

asset_id
sector_id
weight
classification_type  (primary / secondary)


3. sector_snapshot
------------------

Hier wordt per tijdframe de sectorprestatie opgeslagen.

Metrics die worden opgeslagen:

coin_count
breadth_ratio
avg_return_pct
volume_ratio
sector_score
market_relative_score
leader_asset_id
laggard_asset_id

Breadth definitie:

breadth_ratio =
coins_up / coins_active

Dit voorkomt dat één coin een sectorbeweging domineert.


4. sector_regime
----------------

Interpretatie van sectorstatus.

Regime labels:

leading
improving
neutral
weakening
lagging
breakout
exhaustion

Velden:

sector_id
ts_utc
timeframe
regime_label
confidence_score
persistence_bars
rank_in_market


SECTOR SCORE LOGICA
-------------------

Sector sterkte wordt berekend met een gecombineerde score.

Basisformule:

sector_score =
0.35 * weighted_return
+ 0.25 * breadth
+ 0.20 * volume_ratio
+ 0.20 * persistence

Waarbij:

weighted_return
= gemiddelde return van sectorcoins

breadth
= hoeveel coins meedoen aan de move

volume_ratio
= stijgt volume mee

persistence
= hoe lang loopt de sector al


MARKET RELATIVE STRENGTH
------------------------

Sectoren worden ook vergeleken met de totale markt.

market_rel_score =
sector_score − market_baseline

Hierdoor lijken bij een algemene pump niet alle sectoren automatisch sterk.


SECTOR LEADER DETECTION
-----------------------

Bij elke snapshot slaan we ook op:

leader_asset_id
laggard_asset_id

Hiermee kan later worden geanalyseerd:

- welke coin een sector startte
- welke coins volgden
- sector breadth vs single leader pumps


SECTOR USE CASES IN SYNTH
-------------------------

1. Asset ranking verbetering

Nieuwe formule:

final_asset_score =
0.55 * asset_signal
+ 0.25 * sector_strength
+ 0.10 * sector_breadth
+ 0.10 * market_context

Coins krijgen dus een bonus wanneer hun sector sterk is.


2. Narrative detection

Voorbeeld:

AI sector → leading
DeFi → improving
NFT → lagging

Dit helpt bij het herkennen van altcoin rotaties.


3. Capital rotation tracking

Sector snapshots kunnen worden gebruikt om rotaties te detecteren:

AI → DeFi → Gaming → Memes

Dit patroon komt vaak voor tijdens altcoin cycles.


DATA PIPELINE
-------------

De sector module hangt achter de bestaande feature pipeline.

candles
   ↓
candle_feat
   ↓
asset returns
   ↓
sector aggregation
   ↓
sector_snapshot
   ↓
sector_regime

Sectoranalyse gebruikt dus bestaande asset features.


SECTOR TAXONOMY (VOORBEELD)
---------------------------

L1
L2
AI
DATA
DEFI
DEX
PERPS
NFT
GAMING
MEME
ORACLE
PRIVACY
PAYMENTS
BTC_ECOSYSTEM
RWA

Coins kunnen meerdere sectoren hebben.


ONTWERPKEUZE
------------

Sector classificatie start handmatig.

Voordelen:

- stabiel
- uitlegbaar
- minder ruis

Later kunnen dynamische overlays worden toegevoegd:

AI narrative
Solana ecosystem
Meme cycle
Exchange tokens


VERWACHTE VOORDELEN VOOR SYNTH
-------------------------------

De sector module maakt het mogelijk om:

- sector leadership te detecteren
- sector rotaties te herkennen
- narrative momentum te analyseren
- portfolio sector exposure te meten

Dit is een grote verbetering t.o.v. alleen indicator-based trading.


VOLGENDE ONTWIKKELSTAPPEN
-------------------------

1. sector tabellen integreren in MariaDB
2. asset_sector_map vullen
3. sector_snapshot builder implementeren
4. sector_regime classificatie toevoegen
5. sector leaderboards bouwen
6. sector score integreren in asset ranking


LANGE TERMIJN UITBREIDINGEN
---------------------------

sector momentum dashboard
capital rotation index
narrative detector
ecosystem strength analyse (Solana / ETH etc)
ML sector clustering


Dit document beschrijft het volledige ontwerp van de Synth sector module
zoals besproken in deze chat en kan direct als context worden gebruikt
in een nieuwe Synth ontwikkelchat.
