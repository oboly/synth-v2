# Strategy Scoreboard V1 Findings

## Scope

This note documents the first interpretation of:

`data/research/strategy_scoreboard_v1/run_20260525T120428Z/`

It is research evidence only.

It is not live permission.
It does not change:

- `selection_engine`
- `decision_gate`
- `execution_planner`
- `executor`

## Promotion State Counts

- `BLOCKED_NEEDS_REPLAY_SAFE_VALIDATION = 45`
- `REJECT_NEGATIVE_EXPECTANCY = 5`
- `RESEARCH_PROMOTION_CANDIDATE = 3`
- `WATCH_MORE_DATA = 12`

The scoreboard remains conservative by design. Most rows stay blocked because they are either baseline/comparator rows, invalid future-target diagnostics, or broad context buckets that still need replay-safe narrowing.

## Strongest Candidate

The clearest initial candidate is:

`TP_ALIGNMENT_STRICT_FUTURE|TP_NEAR_FIB_EXTENSION`

This bucket is the only family/signal combination that produced multiple `RESEARCH_PROMOTION_CANDIDATE` rows on meaningful sample counts.

Promoted horizons:

- `24h`: samples `2511`, avg `+0.506%`, median `+0.393%`, winrate `56.59%`, profit_factor `1.64`, excess `+0.693%`
- `48h`: samples `2502`, avg `+0.351%`, median `+0.335%`, winrate `55.04%`, profit_factor `1.32`, excess `+0.598%`
- `12h`: samples `2511`, avg `+0.427%`, median `+0.306%`, winrate `57.59%`, profit_factor `1.73`, excess `+0.414%`

Interpretation:

- `TP_NEAR_FIB_EXTENSION` appears materially better than `TP_SR_ONLY`
- the edge survives against the buy-and-hold comparator on these horizons
- the sample size is large enough to take seriously as a research candidate

## Watch List

Still promising, but not yet above the conservative v1 promotion bar:

- `TP_ALIGNMENT_STRICT_FUTURE|TP_NEAR_FIB_EXTENSION|8h`
- `TP_ALIGNMENT_STRICT_FUTURE|TP_FIB_EXTENSION_1272_1618` across horizons
- `VALID_FUTURE_TP_TARGET|VALID` across horizons

Interpretation:

- the `8h` near-extension bucket is positive, but excess return is smaller than the 12h/24h/48h cases
- strict-future fib-extension buckets are generally positive, but not yet strong enough for promotion
- `VALID_FUTURE_TP_TARGET|VALID` is directionally constructive, but still too broad as a standalone bucket

## Weak Or Rejected Buckets

Weak or explicitly negative buckets include:

- `TP_SR_ONLY` on longer horizons
- invalid future TP targets
- `TP_WRONG_SIDE_FOR_LEG`
- `TP_AT_OR_NEAR_PRICE`

Observed pattern:

- `TP_ALIGNMENT_STRICT_FUTURE|TP_SR_ONLY` turns negative at `4h`, `12h`, `24h`, and `48h`, with the weakest longer-horizon outcomes at `24h` and `48h`
- `VALID_FUTURE_TP_TARGET|INVALID` is consistently negative and remains blocked
- `TP_SIDE|TP_WRONG_SIDE_FOR_LEG` is negative across horizons and remains blocked
- `TP_SIDE|TP_AT_OR_NEAR_PRICE` is clearly weak and remains blocked

Interpretation:

- wrong-side or already-contaminated targets are not just noisy; they are directionally harmful
- plain SR-only TP context does not look comparable to near-extension TP context

## Method Interpretation

The recent strict-future patch matters.

Before strict-future-only hit logic, TP-hit rates were contaminated by sample-candle inclusion and already-crossed/wrong-side targets.

Current reading:

- strict-future metrics fixed the prior hit-rate contamination enough to make scoreboard interpretation materially more trustworthy
- this improves confidence in the relative separation between `TP_NEAR_FIB_EXTENSION` and `TP_SR_ONLY`
- it does not yet make the result replay-safe for trading use

## Boundary

This is still research evidence only.

No bucket here is approved for:

- live trading
- paper trading permission
- direct execution logic
- `selection_engine` changes
- `decision_gate` changes
- execution usage

## Next Validation

The next step should not be immediate promotion.

The next validation step is to join scoreboard evidence with:

- discovered regime buckets
- symbol buckets

That means:

1. test whether the `TP_NEAR_FIB_EXTENSION` edge survives by discovered regime
2. test whether it survives by symbol or concentrated symbol clusters
3. only then consider replay-safe promotion work

Until that is done, the current outcome is:

- strong research signal found
- no operational promotion yet
