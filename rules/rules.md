# Cockpit Checklist — rules.md
> The agent CANNOT recommend any trade that fails any condition in this file.
> Read this file FIRST. Every session. No exceptions.

---

## 1. Trend Filter — EMA Fanning (Required before any signal)

| Condition | Rule |
|-----------|------|
| **Bullish valid** | 8 EMA > 20 EMA > 50 EMA (ordered by proximity to price) |
| **Bearish valid** | 8 EMA < 20 EMA < 50 EMA (ordered by proximity to price) |
| **INVALID** | EMAs crossing, converging, or flat = NO TRADE. Trend is consolidating. |

**Agent instruction:** If EMAs are not cleanly fanned, classify asset as `NEUTRAL`. Do not force a bias.

---

## 2. Price Action Validation — 30% Body Rule

A signal candle is only valid when:

- **Bullish continuation:** Open AND Close occur within the **upper 30%** of the candle's full range.
- **Bearish continuation:** Open AND Close occur within the **lower 30%** of the candle's full range.

**Agent instruction:** Calculate `range = High - Low`. Calculate `upper_30 = High - (range * 0.30)`. Reject any candle where Close falls below `upper_30` on a bullish signal.

---

## 3. Harmonic Pattern Validation

### Gartley Pattern Rules

```
B-Point:  MUST hit 0.618 retracement of X→A leg
          EXCLUSION: If price touches 0.786 retracement → INVALIDATE Gartley
          ACTION: Reclassify as potential Butterfly pattern

C-Point:  MUST hit >= 0.618 retracement of A→B leg
          HARD RULE: Must NOT penetrate the A-point (not even by 1 pip)

D-Point:  Completion at 1.27 Fibonacci extension of A→B leg
          → This is the entry zone
```

**Reclassification logic:**
- `B touches 0.786` → Reclassify to **Butterfly** or mark **INVALID GARTLEY**
- `C violates A` → Pattern **INVALID**, discard entirely

---

## 4. Risk Management — ATR(7) Dynamic Stop

```
Stop_Loss = Entry_Price - (ATR(7) * multiplier)
```

- Use **ATR period = 7** (not 14, not default)
- Multiplier provides "breathing room" — adjust per volatility regime
- **NO SIGNAL WITHOUT A STOP.** Any setup missing ATR(7) stop is blocked.
- Minimum Risk/Reward benchmark: **1:1**

---

## 5. Capital Conservation — The 90-90-90 Safeguard

> 90% of traders lose 90% of their capital in 90 days.

The agent treats **capital preservation as the primary success metric**, not profit.

- Log `90-90-90 Metric` (% capital remaining) in every decisions-log entry
- Any session that ends with capital loss must trigger a behavioral review
- The agent MUST flag when drawdown patterns mirror the 90-90-90 trajectory

---

## 6. Execution Environment Rules

| Rule | Detail |
|------|--------|
| **A-Book only** | Broker profits from commissions, NOT from trader losses |
| **B-Book flag** | If broker takes opposite side of trade → FLAG immediately |
| **No signal services** | External signals, gurus, influencers = BLOCKED |
| **No toxic forums** | Trading chat rooms, social media calls = IGNORED |
| **Silly Donation block** | Revenge trade, FOMO entry, impulsive setup = BLOCKED |

---

## 7. Watch List

`BTC` · `ETH` · `SOL` · `XRP` · `LINK` · `PEPE`

Weekly (1W) timeframe is assessed FIRST for every asset before any lower timeframe analysis.

---

## 8. Advanced Market Structure (AMS)

> Stacks on top of §1–4. Does not replace the Cockpit Checklist.
> Source: brother's Advanced Market Structure strategy.

### Daily bias (previous completed day)

| Previous day candle | Daily bias | Allowed direction |
|---------------------|------------|-------------------|
| **Green** (close ≥ open) | **BUY only** | Long setups only |
| **Red** (close < open) | **SELL only** | Short setups only |

**Agent instruction:** Mark **today's daily open** as the session anchor price.

### 1W vs daily alignment

| 1W trend | Prev day | Action |
|----------|----------|--------|
| FANNING-BULL | Green (BUY) | Confirmed buy bias — proceed to 1H |
| FANNING-BEAR | Red (SELL) | Confirmed sell bias — proceed to 1H |
| FANNING-BULL | Red (SELL) | **Bias conflict — WAIT** |
| FANNING-BEAR | Green (BUY) | **Bias conflict — WAIT** |

### 1H pullback (required before entry)

Entry only after a counter-trend sequence on **1H**, then the first candle matching daily bias:

- **Green daily bias (BUY):** wait for a sequence of **red** 1H candles, then **first green** 1H candle = entry trigger
- **Red daily bias (SELL):** wait for a sequence of **green** 1H candles, then **first red** 1H candle = entry trigger

**Agent instruction:** No entry until 1H pullback completes. Weekly EMA + body rule + ATR(7) still apply after AMS gates pass.
