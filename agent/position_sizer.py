"""
position_sizer.py — Position sizing enforcer aligned to rules.md §4.

Converts a validated SignalResult into a concrete position size (units / contracts)
using fixed fractional risk. Never called before check_signal passes.

Usage:
    from position_sizer import size_position, print_trade_card
    card = size_position(signal, account_balance=10_000)
    print_trade_card(card)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from signal_checker import SignalResult, SignalType


# ── Defaults (override via size_position kwargs) ──────────────────────────────
DEFAULT_RISK_PCT   = 1.0    # % of account risked per 1R (aligns with backtester.py)
MAX_RISK_PCT       = 2.0    # Hard cap — never exceed this regardless of caller
MIN_POSITION_VALUE = 1.0    # $1 minimum (sanity check for tiny accounts)


@dataclass
class TradeCard:
    """Complete, actionable trade specification ready to execute."""
    ticker:           str
    timeframe:        str
    direction:        str           # "LONG" | "SHORT"

    entry_price:      float
    stop_loss:        float
    target_1r:        float

    risk_per_unit:    float         # |entry - stop|
    account_balance:  float
    risk_pct:         float         # actual % being risked
    risk_dollars:     float         # $ amount at risk
    position_units:   float         # units to buy/sell
    position_value:   float         # notional $ value at entry

    r_r_ratio:        float         # Risk:Reward (always 1.0 here — 1:1 minimum)
    capital_after_loss:  float      # Account value if stop is hit
    capital_after_win:   float      # Account value if target is hit

    warning: Optional[str] = None

    def to_console(self) -> str:
        warn_line = f"\n  ⚠  {self.warning}" if self.warning else ""
        return (
            f"\n{'═'*55}\n"
            f"  TRADE CARD: {self.ticker} ({self.timeframe}) — {self.direction}\n"
            f"{'═'*55}\n"
            f"  Entry:          {self.entry_price:.6g}\n"
            f"  Stop Loss:      {self.stop_loss:.6g}  "
            f"({'↓' if self.direction=='LONG' else '↑'} {self.risk_per_unit:.6g} per unit)\n"
            f"  Target 1R:      {self.target_1r:.6g}  (1:1 minimum)\n"
            f"{'─'*55}\n"
            f"  Account:        ${self.account_balance:,.2f}\n"
            f"  Risk:           {self.risk_pct:.1f}%  →  ${self.risk_dollars:,.2f}\n"
            f"  Position size:  {self.position_units:.6g} units\n"
            f"  Notional value: ${self.position_value:,.2f}\n"
            f"{'─'*55}\n"
            f"  If stop hit:    ${self.capital_after_loss:,.2f}  "
            f"(-${self.risk_dollars:,.2f})\n"
            f"  If target hit:  ${self.capital_after_win:,.2f}  "
            f"(+${self.risk_dollars:,.2f})\n"
            f"{'═'*55}"
            f"{warn_line}"
        )


def size_position(
    signal: SignalResult,
    account_balance: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    capital_pct: float = 100.0,
) -> TradeCard:
    """
    Calculate position size for a validated signal.

    Args:
        signal:          A passing SignalResult from signal_checker.check_signal
        account_balance: Total account value in USD
        risk_pct:        % of account to risk per trade (default 1%)
        capital_pct:     Current 90-90-90 capital level (reduces risk when < 80%)

    Returns:
        TradeCard with all sizing fields populated.
    """
    if not signal.passed:
        raise ValueError(
            f"size_position called on blocked signal for {signal.ticker}. "
            "Only call after check_signal passes."
        )

    warning: Optional[str] = None

    # ── Capital conservation: reduce risk at orange/red thresholds ────────────
    effective_risk_pct = risk_pct
    if capital_pct < 80:
        effective_risk_pct = risk_pct * 0.5
        warning = (
            f"Capital at {capital_pct:.0f}% (ORANGE) — "
            f"risk halved to {effective_risk_pct:.1f}% per rules.md"
        )
    elif capital_pct < 90:
        effective_risk_pct = risk_pct * 0.75
        warning = (
            f"Capital at {capital_pct:.0f}% (YELLOW) — "
            f"risk reduced to {effective_risk_pct:.1f}% per rules.md"
        )

    # Hard cap
    effective_risk_pct = min(effective_risk_pct, MAX_RISK_PCT)

    # ── Core calculation ──────────────────────────────────────────────────────
    risk_dollars  = account_balance * (effective_risk_pct / 100)
    risk_per_unit = abs(signal.entry_price - signal.stop_loss)

    if risk_per_unit == 0:
        raise ValueError("stop_loss == entry_price: zero-risk setup, cannot size")

    position_units = risk_dollars / risk_per_unit
    position_value = position_units * signal.entry_price

    # Sanity floor
    if position_value < MIN_POSITION_VALUE:
        warning = (warning or "") + (
            f" Position value ${position_value:.2f} below ${MIN_POSITION_VALUE} minimum."
        )

    r_r = abs(signal.target_1r - signal.entry_price) / risk_per_unit

    direction = signal.signal_type.value   # "LONG" or "SHORT"

    capital_after_loss = account_balance - risk_dollars
    capital_after_win  = account_balance + risk_dollars

    return TradeCard(
        ticker=signal.ticker,
        timeframe=signal.timeframe,
        direction=direction,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target_1r=signal.target_1r,
        risk_per_unit=risk_per_unit,
        account_balance=account_balance,
        risk_pct=effective_risk_pct,
        risk_dollars=risk_dollars,
        position_units=position_units,
        position_value=position_value,
        r_r_ratio=r_r,
        capital_after_loss=capital_after_loss,
        capital_after_win=capital_after_win,
        warning=warning,
    )


def size_all_signals(
    signals: list[SignalResult],
    account_balance: float,
    risk_pct: float = DEFAULT_RISK_PCT,
    capital_pct: float = 100.0,
) -> list[TradeCard]:
    """Size every passing signal in a checklist result list."""
    cards = []
    for sig in signals:
        if sig.passed:
            try:
                card = size_position(sig, account_balance, risk_pct, capital_pct)
                cards.append(card)
            except ValueError as e:
                print(f"  ⚠ Sizing skipped for {sig.ticker}: {e}")
    return cards


def print_trade_card(card: TradeCard) -> None:
    print(card.to_console())


if __name__ == "__main__":
    from data_fetcher import fetch_all_assets
    from signal_checker import run_full_checklist

    print("Fetching 1W data...")
    weekly_data = fetch_all_assets(timeframe="1w")
    results = run_full_checklist(weekly_data, timeframe="1w", capital_pct=100.0)

    ACCOUNT = 10_000.0
    cards   = size_all_signals(results, account_balance=ACCOUNT)

    if cards:
        print(f"\n{'='*55}")
        print(f"  POSITION SIZING  |  Account: ${ACCOUNT:,.2f}")
        print(f"{'='*55}")
        for card in cards:
            print_trade_card(card)
    else:
        print("\nNo valid signals to size today.")
