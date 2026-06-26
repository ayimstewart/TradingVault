"""
apex_guard.py — Apex Trader Funding trailing drawdown protection.

Reads account state from ~/.tradingvault/apex_state.json and blocks any
futures signal that would put the account within danger-zone distance of
the trailing drawdown floor.

Reference: rules/apex_rules.md

Usage:
    python3 apex_guard.py                    # show current state
    python3 apex_guard.py --atr 0.97         # check guard for given ATR(7)
    python3 apex_guard.py --update-balance 51200  # record end-of-day balance
    python3 apex_guard.py --update-pnl -350       # record today's P&L
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


STATE_FILE   = Path.home() / ".tradingvault" / "apex_state.json"
VAULT_ROOT   = Path(__file__).parent.parent
DECISIONS_LOG = VAULT_ROOT / "logs" / "decisions-log.md"

DANGER_ZONE_MULTIPLIER = 1.5   # block if within 1.5 × ATR(7) of floor


# ── Default account template (PA-50K) ────────────────────────────────────────

DEFAULT_STATE = {
    "account_size": 50_000,
    "trailing_drawdown": 2_500,
    "daily_loss_limit": 2_500,
    "peak_eod_balance": 50_000,
    "current_balance": 50_000,
    "today_pnl": 0.0,
    "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
}


# ── State I/O ─────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(DEFAULT_STATE, indent=2))
    print(f"[apex_guard] Created default state file: {STATE_FILE}")
    print("  Edit it to match your actual Apex account.")
    return DEFAULT_STATE.copy()


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── Guard result ──────────────────────────────────────────────────────────────

@dataclass
class ApexGuardResult:
    passed: bool
    reason: str
    current_balance: float
    drawdown_floor: float
    distance_to_floor: float
    daily_pnl: float
    daily_limit: float
    danger_zone_value: float   # 1.5 × ATR(7) in dollars
    atr_used: float

    def to_console(self) -> str:
        status = "PASS" if self.passed else "BLOCK"
        bar    = "═" * 55
        return (
            f"\n{bar}\n"
            f"  APEX GUARD — {status}\n"
            f"{bar}\n"
            f"  Balance:        ${self.current_balance:,.2f}\n"
            f"  Drawdown floor: ${self.drawdown_floor:,.2f}\n"
            f"  Distance:       ${self.distance_to_floor:,.2f}   "
            f"({'SAFE' if self.distance_to_floor > self.danger_zone_value else 'DANGER'})\n"
            f"  Danger zone:    ${self.danger_zone_value:,.2f}  (1.5 × ATR {self.atr_used:.4f})\n"
            f"  Today P&L:      ${self.daily_pnl:+,.2f}  (limit: -${self.daily_limit:,.2f})\n"
            f"{'─'*55}\n"
            f"  Result: {self.reason}\n"
            f"{bar}\n"
        )


# ── Core guard logic ──────────────────────────────────────────────────────────

def check_apex_guard(atr_7: float = 0.0) -> ApexGuardResult:
    """
    Run the full trailing drawdown check for the current session.

    Args:
        atr_7: ATR(7) value of the instrument about to be traded (in price units).
               If 0, danger zone check is skipped (only hard floor is checked).

    Returns:
        ApexGuardResult — check .passed before generating any signal.
    """
    state = _load_state()

    current_balance = float(state["current_balance"])
    peak_eod        = float(state["peak_eod_balance"])
    trailing_dd     = float(state["trailing_drawdown"])
    daily_limit     = float(state["daily_loss_limit"])
    today_pnl       = float(state["today_pnl"])

    drawdown_floor     = peak_eod - trailing_dd
    distance_to_floor  = current_balance - drawdown_floor
    danger_zone_value  = atr_7 * DANGER_ZONE_MULTIPLIER if atr_7 > 0 else 0.0

    # ── Hard block 1: balance at or below floor ───────────────────────────────
    if current_balance <= drawdown_floor:
        reason = (
            f"ACCOUNT BLOWN — balance ${current_balance:,.2f} at or below "
            f"trailing floor ${drawdown_floor:,.2f}. No new signals."
        )
        _log_block(reason, current_balance, drawdown_floor)
        return ApexGuardResult(
            passed=False, reason=reason,
            current_balance=current_balance, drawdown_floor=drawdown_floor,
            distance_to_floor=distance_to_floor, daily_pnl=today_pnl,
            daily_limit=daily_limit, danger_zone_value=danger_zone_value,
            atr_used=atr_7,
        )

    # ── Hard block 2: daily loss limit hit ───────────────────────────────────
    if today_pnl <= -abs(daily_limit):
        reason = (
            f"DAILY LIMIT HIT — today's P&L ${today_pnl:+,.2f} reached "
            f"limit -${daily_limit:,.2f}. No more signals today."
        )
        _log_block(reason, current_balance, drawdown_floor)
        return ApexGuardResult(
            passed=False, reason=reason,
            current_balance=current_balance, drawdown_floor=drawdown_floor,
            distance_to_floor=distance_to_floor, daily_pnl=today_pnl,
            daily_limit=daily_limit, danger_zone_value=danger_zone_value,
            atr_used=atr_7,
        )

    # ── Soft block: within danger zone (1.5 × ATR of floor) ──────────────────
    if atr_7 > 0 and distance_to_floor <= danger_zone_value:
        reason = (
            f"DANGER ZONE — distance to floor ${distance_to_floor:,.2f} is within "
            f"1.5 × ATR ({danger_zone_value:,.2f}). Signal blocked per apex_rules.md."
        )
        _log_block(reason, current_balance, drawdown_floor)
        return ApexGuardResult(
            passed=False, reason=reason,
            current_balance=current_balance, drawdown_floor=drawdown_floor,
            distance_to_floor=distance_to_floor, daily_pnl=today_pnl,
            daily_limit=daily_limit, danger_zone_value=danger_zone_value,
            atr_used=atr_7,
        )

    reason = (
        f"CLEAR — balance ${current_balance:,.2f} is ${distance_to_floor:,.2f} "
        f"above floor ${drawdown_floor:,.2f}. Daily P&L ${today_pnl:+,.2f}."
    )
    return ApexGuardResult(
        passed=True, reason=reason,
        current_balance=current_balance, drawdown_floor=drawdown_floor,
        distance_to_floor=distance_to_floor, daily_pnl=today_pnl,
        daily_limit=daily_limit, danger_zone_value=danger_zone_value,
        atr_used=atr_7,
    )


# ── State update helpers ──────────────────────────────────────────────────────

def update_eod_balance(new_balance: float) -> None:
    """
    Call at end of each trading day.
    Advances peak_eod_balance if new_balance is higher (trailing ratchet).
    """
    state = _load_state()
    old_peak = float(state["peak_eod_balance"])
    state["current_balance"] = new_balance
    if new_balance > old_peak:
        state["peak_eod_balance"] = new_balance
        print(f"[apex_guard] Peak EOD raised: ${old_peak:,.2f} → ${new_balance:,.2f}")
        print(f"             Trailing floor:  ${new_balance - state['trailing_drawdown']:,.2f}")
    state["today_pnl"] = 0.0   # reset daily P&L on EOD update
    _save_state(state)
    print(f"[apex_guard] Balance updated to ${new_balance:,.2f}")


def update_today_pnl(pnl_delta: float) -> None:
    """Add a realized P&L increment to today's running total."""
    state = _load_state()
    state["today_pnl"] = float(state.get("today_pnl", 0)) + pnl_delta
    state["current_balance"] = float(state["current_balance"]) + pnl_delta
    _save_state(state)
    print(f"[apex_guard] Today P&L → ${state['today_pnl']:+,.2f}  |  Balance → ${state['current_balance']:,.2f}")


# ── Decision log ─────────────────────────────────────────────────────────────

def _log_block(reason: str, balance: float, floor: float) -> None:
    """Append an Apex block entry to decisions-log.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = (
        f"\n| {now} | APEX BLOCK | N/A | — | — | — | — | "
        f"Balance ${balance:,.2f}, floor ${floor:,.2f}: {reason} |\n"
    )
    try:
        with open(DECISIONS_LOG, "a") as f:
            f.write(entry)
    except OSError:
        pass   # log write failure must never block trading-session code


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Apex trailing drawdown guard")
    parser.add_argument("--atr", type=float, default=0.0,
                        help="ATR(7) value of instrument (default: 0 = skip danger zone)")
    parser.add_argument("--update-balance", type=float, metavar="BALANCE",
                        help="Record end-of-day balance and advance trailing peak")
    parser.add_argument("--update-pnl", type=float, metavar="DELTA",
                        help="Add realized P&L delta to today's running total")
    args = parser.parse_args()

    if args.update_balance is not None:
        update_eod_balance(args.update_balance)
        return

    if args.update_pnl is not None:
        update_today_pnl(args.update_pnl)
        return

    result = check_apex_guard(atr_7=args.atr)
    print(result.to_console())


if __name__ == "__main__":
    main()
