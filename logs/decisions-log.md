# Decisions Log — Persistent Memory

> Every signal identified must produce one row in this table.
> This file tracks both technical AND behavioral data.
> The agent reads the last 5 entries before every new recommendation.

---

## Log Table

| Date | Signal Type | Asset | Timeframe | CTS Score | Emotional State (1–10) | Error / Silly Donation | 90-90-90 Metric | Notes |
|------|-------------|-------|-----------|-----------|------------------------|------------------------|-----------------|-------|
| YYYY-MM-DD | e.g. 3-Bar Reversal | BTC | 4H | Confluence rating | Fear=1 / Greed=10 | Logic violation? Y/N | % capital remaining | Context |

---

## Column Definitions

| Column | Description |
|--------|-------------|
| **Date** | ISO format: YYYY-MM-DD |
| **Signal Type** | e.g. 3-Bar Reversal, Trend Continuation, Gartley D-Point, Butterfly |
| **Asset** | From watch list: BTC, ETH, SOL, XRP, LINK, PEPE |
| **Timeframe** | 1W → 1D → 4H → 1H (weekly bias established first) |
| **CTS Score** | Confluence score: how many checklist items confirmed |
| **Emotional State** | 1 = pure fear, 10 = pure greed. Log the market context, not personal feeling |
| **Error / Silly Donation** | Was any rule violated? What was the trigger? FOMO / Revenge / Impulse |
| **90-90-90 Metric** | Current % of starting capital remaining this cycle |
| **Notes** | Free text: what was the setup, what happened, what to learn |

---

## Silly Donation Registry

> Trades that violated the Cockpit Checklist. Logged here for behavioral pattern analysis.

| Date | Asset | Violation | Rule Broken | Capital Impact |
|------|-------|-----------|-------------|----------------|
| — | — | — | — | — |

---

## Behavioral Pattern Tracker

Agent reviews this section weekly to identify recurring error types:

- [ ] FOMO entries (chasing moves already in progress)
- [ ] Revenge trading (oversizing after a loss)
- [ ] Impulsive entries (no checklist validation)
- [ ] B-Book broker behavior detected
- [ ] Signal service contamination
