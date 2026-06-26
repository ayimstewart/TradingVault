# Apex Trader Funding — Trailing Drawdown Rules
> Source of truth for apex_guard.py. Read before every futures signal.

---

## What the Trailing Drawdown Is

Apex uses a **trailing drawdown** based on your highest **end-of-day** equity
(not intraday high). The drawdown threshold follows your balance upward but
never comes back down.

| Account Size | Trailing Drawdown | Max Daily Loss |
|-------------|-------------------|----------------|
| PA-25K      | $1,500            | $1,000         |
| PA-50K      | $2,500            | $1,000         |
| PA-75K      | $2,750            | $2,750         |
| PA-100K     | $3,000            | $3,000         |
| PA-150K     | $5,000            | $5,000         |
| PA-250K     | $6,500            | $6,500         |

---

## How the Trailing Stop Calculates

```
drawdown_floor = peak_end_of_day_balance - trailing_drawdown_amount

IF current_balance <= drawdown_floor:
    ACCOUNT BLOWN → session ends, no new orders
```

**Example — PA-50K ($2,500 trailing):**
- Start: $50,000 → floor at $47,500
- Day 1 close: $51,200 → floor rises to $48,700
- Day 2 close: $52,000 → floor rises to $49,500
- Day 3 intraday drops to $49,400 → BLOWN (floor was $49,500)

**Key rule: the floor only moves UP, never down.**

---

## Daily Loss Limit (separate from trailing)

Each trading day has a separate hard daily loss cap (see table above).
Hitting the daily limit also ends that day's trading — but does NOT blow
the account if you are still above the trailing floor.

---

## Danger Zone — Pre-Signal Check

Before generating any futures signal, `apex_guard.py` checks:

```python
DANGER_ZONE_ATR_MULTIPLIER = 1.5  # block if within 1.5 ATR of floor

distance_to_floor = current_balance - drawdown_floor
atr_value = <ATR(7) of the instrument>
danger_zone = atr_value * DANGER_ZONE_ATR_MULTIPLIER

if distance_to_floor <= danger_zone:
    SIGNAL BLOCKED — too close to trailing drawdown floor
```

This prevents a single losing trade from hitting the floor.

---

## Hard Blocks (Non-Negotiable)

| Condition | Action |
|-----------|--------|
| balance <= drawdown_floor | STOP — account at risk, no new signals |
| distance_to_floor <= 1.5 × ATR(7) | BLOCK signal + log to decisions-log.md |
| daily_loss >= daily_limit | STOP for today — no more signals |
| Signal has no ATR(7) stop | BLOCKED (rules.md §4, redundant check) |

---

## Integration with Vault

- `apex_guard.py` reads these thresholds and enforces them before any futures signal
- All blocks are logged to `logs/decisions-log.md` with reason
- Apex account balance is tracked manually — update `~/.tradingvault/apex_state.json`
  after every session close

---

## Apex Account State File

`~/.tradingvault/apex_state.json` (never committed to git):

```json
{
  "account_size": 50000,
  "trailing_drawdown": 2500,
  "daily_loss_limit": 2500,
  "peak_eod_balance": 50000,
  "current_balance": 50000,
  "today_pnl": 0,
  "last_updated": "2026-06-26"
}
```

Update `peak_eod_balance` at end of each trading day if balance is higher than previous peak.
