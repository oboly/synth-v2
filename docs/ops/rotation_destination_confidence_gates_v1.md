# Rotation Destination Confidence Gates v1

Rotation destination display now separates eligibility from evidence completeness.

Market review refs remain broad market-only comparison symbols. Rotation destinations are stricter:
the candidate must pass destination eligibility and have clean destination confidence.

Destination confidence uses existing reporting context only:

- paper advice `aplus_bucket`
- Market Breath A+ legacy freshness and block-strength labels
- Market Breath/curve structure fields such as confidence, momentum, and relative strength

Display labels:

- `HIGH_CONFIDENCE_DESTINATION`: fresh/aging A+ context plus usable curve structure.
- `MEDIUM_CONFIDENCE_DESTINATION`: A+ context is usable, but curve structure is weak.
- `LOW_CONFIDENCE_DESTINATION`: A+ is missing, stale, avoid/distorted, or otherwise not clean.
- `MARKET_ONLY_DESTINATION`: market-only evidence without confirming A+/curve context.
- `MISSING_APLUS_CONTEXT`: evidence label when A+ context is absent or unknown.
- `STALE_APLUS_CONTEXT`: evidence label when A+ context is stale or very stale.
- `APLUS_AVOID_OR_DISTORTED`: evidence label when A+ says avoid or the legacy block strength is avoid-like.
- `WEAK_CURVE_STRUCTURE`: evidence label when market-breath confidence or structure is weak.

Low-confidence and market-only candidates can still appear in candidate diagnostics and market review
refs. They are not shown as clean rotation destinations.

Dashboard note:

> Rotation destination confidence includes market structure plus available A+/curve context. Missing A+ lowers confidence; it is not trade advice.

Boundary: reporting/dashboard only. No selection engine, decision gate, execution planner, executor,
broker, order, or account mutation behavior changes.
