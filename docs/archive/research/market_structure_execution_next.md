# Market Structure → Execution Next (Synth v2)

## 📌 Doel
Overgang van:
- Context analyse (zones + fib + volume)

naar:
- Daadwerkelijke order placement (execution layer)

---

## 🧠 Huidige staat (samengevat)

Market structure layer levert nu:

- zone_state
- zone distances (bps)
- fib_state
- fib_level
- fib_distance_bps
- fib_confluence_score
- volume_alignment_score
- context_score

👉 Dit vormt de **input voor execution**

---

## ⚙️ Execution Filosofie

### 1. Passive-first
- altijd starten met limit orders
- nooit direct market orders

### 2. Spread capture
- buy: best bid + 1 tick
- sell: best ask - 1 tick

### 3. Queue priority
- doel: vooraan in orderbook staan

### 4. Reprice loop
- cancel/replace indien nodig
- max_reprices
- max_wait_seconds
- max_chase_bps

### 5. Escalation
- passive → aggressive limit

### 6. Abort
- bij invalidation van context

---

## 🧩 Architectuur

strategy_signal_context  
        ↓  
decision_engine  
        ↓  
execution_planner  
        ↓  
execution_intent  
        ↓  
execution_worker  
        ↓  
exchange (Bitvavo)

---

## 🚀 Volgende stappen

1. Execution planner v1 bouwen  
2. Execution worker skeleton  
3. Bitvavo integratie  
4. Reprice loop  
5. Safety logic  

