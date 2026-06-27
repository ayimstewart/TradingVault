# Advanced Market Structure Strategy

## Core Concept
Momentum persistence trading based on previous day candle color.

## Daily Bias Rule
- Previous day GREEN candle → Buy bias today (long entries only)
- Previous day RED candle → Sell bias today (short entries only)

## Execution Sequence
1. Check previous day candle color on Daily chart
2. Mark today's Daily Open price as anchor
3. Drop to 1H chart and wait for counter-trend pullback
4. Entry trigger:
   - Bull bias: wait for red 1H candles to fall, 
     enter at close of first GREEN 1H candle after sequence
   - Bear bias: wait for green 1H candles to rise,
     enter at close of first RED 1H candle after sequence

## Key Rules
- Never chase price — always wait for pullback
- Daily Open is the anchor reference point
- Counter-trend retracement = buying at the low / selling at the high
- Daily bias is non-negotiable for the session

## Integration with Cockpit Checklist
- 1W EMA tablishes weekly trend
- Previous day candle confirms daily momentum
- Both must align before 1H entry is valid
