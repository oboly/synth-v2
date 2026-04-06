# Market Structure Progress — Synth v2

## 📅 Status
- Phase: Market Structure → Context Layer COMPLETE
- Next Phase: Execution Layer (orders, Bitvavo integration)

---

## ✅ Wat werkt nu

### 1. Zone Engine (v1)
- Detectie van support/resistance zones
- Opslag in `zone_observation`
- Active/inactive lifecycle

### 2. Zone Context (v1.5)
Per asset + interval:
- zone_state (AT_SUPPORT / NEAR / NONE)
- distance_to_support / resistance
- distance_to_support_bps / resistance_bps
- zone_confluence_score

---

### 3. Fib Engine (v1)
- Swing-based fib detection
- Retracements + extensions
- Opslag in `fib_observation`

---

### 4. Nearest Fib Context (v1)
Per asset + interval:
- fib_level (0.382 / 0.5 / 0.618 / etc)
- fib_price
- fib_distance_bps
- fib_state (AT_FIB / NEAR_FIB / FAR)

---

### 5. Volume Context (v1)
- volume_ratio
- volume_zscore
- volume_state
- volume_alignment_score

---

### 6. Composite Context Score (v1)
Combineert:
- zone_confluence_score (40%)
- fib_confluence_score (40%)
- volume_alignment_score (20%)

Output:
- `context_score` (0 → 1)

---

## 🧠 Architectuur (huidig)

```text
obs_market_candle
        ↓
zone_observation
fib_observation
        ↓
strategy_signal_context   ← centrale contextlaag
        ↓
views / selection / advice
