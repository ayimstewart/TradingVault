# Session Notes — Morning Brief Log

> Every session starts here. Weekly (1W) bias is established FIRST for each asset.
> No lower timeframe analysis until weekly bias is confirmed.

---

## Morning Brief Template

Copy this block at the start of each session:

```
## Morning Brief — YYYY-MM-DD

### Market Context
- Macro event risk today: [yes/no — what]
- Central bank posture (from NotebookLM query): [summary]
- Overall crypto sentiment: [risk-on / risk-off / neutral]

### Watch List — Weekly (1W) Bias First

| Asset | 1W Trend | EMA Status | 1W Bias | 4H Alignment | Session Bias |
|-------|----------|------------|---------|--------------|--------------|
| BTC   |          |            |         |              |              |
| ETH   |          |            |         |              |              |
| SOL   |          |            |         |              |              |
| XRP   |          |            |         |              |              |
| LINK  |          |            |         |              |              |
| PEPE  |          |            |         |              |              |

EMA Status options: FANNING-BULL / FANNING-BEAR / CONVERGING / FLAT
Session Bias options: BULLISH / BEARISH / NEUTRAL / WAIT

### Priority Assets This Session
1. [Asset] — reason
2. [Asset] — reason
3. [Asset] — reason

### Behavioral Check (Pre-Session)
- Last session result: [win / loss / break-even]
- 90-90-90 Metric: [% capital remaining]
- Emotional risk level: [low / medium / high]
- Silly Donation risk: [none / watch for FOMO / watch for revenge]

### Signals Identified
[Populated during session — link to decisions-log entries]

### Session Close Notes
- What worked:
- What to review:
- Rule violations (if any):
```

---

## Session Archive

> Completed briefs go below this line, newest first.

---

## Morning Brief — 2026-06-26

### Market Context
- Macro event risk today: none confirmed
- Overall crypto sentiment: risk-off (all watch list assets FANNING-BEAR)
- Reference: sources/2026-06-26-morning-brief.md

### Watch List — Weekly (1W) Bias

| Asset | 1W Trend | EMA Status | 1W Bias | ATR(7) | Session Bias |
|-------|----------|------------|---------|--------|--------------|
| BTC | FANNING-BEAR | 8<20<50 | BEARISH | 5695.16 | WAIT |
| ETH | FANNING-BEAR | 8<20<50 | BEARISH | 221.36 | WAIT |
| SOL | FANNING-BEAR | 8<20<50 | BEARISH | 10.13 | WAIT |
| XRP | FANNING-BEAR | 8<20<50 | BEARISH | 0.14 | WAIT |
| LINK | FANNING-BEAR | 8<20<50 | BEARISH | 0.97 | WATCH — Gartley D pending |
| PEPE | FLAT | no data | NEUTRAL | 0.00 | NO TRADE |

### Price Alerts

| Asset | Alert Level | Pattern | Action on Touch |
|-------|-------------|---------|-----------------|
| **LINK** | **$8.4746** | **Gartley D-point** | Re-run harmonic_detector.py — confirm D-point completion, check body rule, calculate entry + ATR(7) stop before signal |

> LINK close: $7.2938 | Distance to alert: +$1.1808 (+16.2%) | ATR(7): $0.9743
> Alert fires ~1.2 ATR above current price — do NOT enter early. Wait for D-point touch + candle confirmation.

### Priority Assets This Session
1. LINK — Gartley D pending at 8.4746; all other assets FANNING-BEAR with no clean setup

### Behavioral Check (Pre-Session)
- Silly Donation risk: watch for FOMO entry before D-point is reached
- Rule: No signal until D-point confirmed + body rule passes + ATR(7) stop set

---
