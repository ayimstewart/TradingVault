"""
entry_finder.py — 4H entry drill-down for 1W FANNING-confirmed assets.

CLAUDE.md rule: "Do NOT drop to 4H until 1W bias confirmed."
This module enforces that gate — it only fetches 4H data for assets where
the weekly bias is FANNING-BULL or FANNING-BEAR.

Usage:
    python3 entry_finder.py

Or integrate into run_session.py after step_4 (checklist):
    from entry_finder import find_4h_entries
    entries = find_4h_entries(weekly_results, account_balance=10_000)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data_fetcher   import fetch_all_assets, WATCH_LIST, fetch_ohlcv, add_ema, add_atr, get_exchange
from signal_checker import SignalResult, SignalType, check_signal
from position_sizer import TradeCard, size_position, print_trade_card

VAULT_ROOT  = Path(__file__).parent.parent
SOURCES_DIR = VAULT_ROOT / "sources"
SOURCES_DIR.mkdir(exist_ok=True)


@dataclass
class EntryOpportunity:
    ticker:       str
    weekly_trend: str           # FANNING-BULL | FANNING-BEAR (gate confirmed)
    signal_4h:    SignalResult
    trade_card:   TradeCard | None = None   # None if account_balance not supplied


def find_4h_entries(
    weekly_results: list[SignalResult],
    account_balance: float | None = None,
    risk_pct: float = 1.0,
    capital_pct: float = 100.0,
    verbose: bool = True,
) -> list[EntryOpportunity]:
    """
    For every asset with a confirmed 1W FANNING bias, fetch 4H data and run
    the Cockpit Checklist. Returns only assets with actionable 4H setups.

    Args:
        weekly_results:   Output of run_full_checklist on 1W data
        account_balance:  If provided, populate TradeCard with position sizing
        risk_pct:         % account risked per trade (default 1%)
        capital_pct:      90-90-90 capital level (reduces risk when < 80%)
        verbose:          Print report to console
    """
    # ── Gate: only assets with confirmed weekly FANNING bias ──────────────────
    fanning_assets = [
        r for r in weekly_results
        if r.ema_trend in ("FANNING-BULL", "FANNING-BEAR")
    ]

    if verbose:
        print(f"\n{'='*55}")
        print(f"  4H ENTRY FINDER — Drill-down on confirmed 1W bias")
        print(f"{'='*55}")
        print(f"  Gate: 1W FANNING confirmed for {len(fanning_assets)} asset(s)")
        if not fanning_assets:
            print(f"  No FANNING assets — nothing to drill into. Wait for weekly setup.")
            print(f"{'─'*55}")

    if not fanning_assets:
        return []

    # ── Fetch 4H data only for gated assets ──────────────────────────────────
    exchange   = get_exchange()
    results: list[EntryOpportunity] = []

    for weekly_sig in fanning_assets:
        ticker = weekly_sig.ticker
        symbol = WATCH_LIST.get(ticker)
        if not symbol:
            if verbose:
                print(f"  {ticker}: symbol not found in WATCH_LIST — skipping")
            continue

        try:
            df_4h = fetch_ohlcv(exchange, symbol, timeframe="4h", limit=100)
            df_4h = add_ema(df_4h)
            df_4h = add_atr(df_4h)
        except Exception as e:
            if verbose:
                print(f"  {ticker}: 4H fetch failed — {e}")
            continue

        signal_4h = check_signal(df_4h, ticker, timeframe="4h", capital_pct=capital_pct)

        trade_card = None
        if signal_4h.passed and account_balance:
            try:
                trade_card = size_position(
                    signal_4h,
                    account_balance=account_balance,
                    risk_pct=risk_pct,
                    capital_pct=capital_pct,
                )
            except ValueError as e:
                if verbose:
                    print(f"  {ticker}: sizing error — {e}")

        opp = EntryOpportunity(
            ticker=ticker,
            weekly_trend=weekly_sig.ema_trend,
            signal_4h=signal_4h,
            trade_card=trade_card,
        )
        results.append(opp)

        if verbose:
            _print_opportunity(opp)

    if verbose:
        _print_summary(results)

    return results


def _print_opportunity(opp: EntryOpportunity) -> None:
    row = opp.signal_4h
    print(f"\n{'─'*55}")
    print(f"  {opp.ticker}  |  1W: {opp.weekly_trend}  →  4H drill-down")
    print(f"{'─'*55}")
    print(f"  4H EMA trend:  {row.ema_trend}")
    print(f"  4H Body rule:  {'PASS' if row.body_rule else 'FAIL'}")
    print(f"  4H ATR(7):     {row.atr_value:.6g}")
    print(f"  4H Signal:     {row.signal_type.value}")
    if row.passed:
        print(f"  ✓ VALID ENTRY")
        print(f"    Entry:     {row.entry_price:.6g}")
        print(f"    Stop:      {row.stop_loss:.6g}")
        print(f"    Target 1R: {row.target_1r:.6g}")
        if opp.trade_card:
            print_trade_card(opp.trade_card)
    else:
        print(f"  ✗ BLOCKED:")
        for reason in row.blocked_by:
            print(f"    · {reason}")


def _print_summary(results: list[EntryOpportunity]) -> None:
    valid   = [r for r in results if r.signal_4h.passed]
    blocked = [r for r in results if not r.signal_4h.passed]

    print(f"\n{'─'*55}")
    print(f"  4H ENTRY SUMMARY")
    print(f"{'─'*55}")
    if valid:
        for v in valid:
            print(f"  ✓ {v.ticker}: {v.signal_4h.signal_type.value} "
                  f"at {v.signal_4h.entry_price:.6g}")
    else:
        print(f"  No valid 4H entries — wait for pullback to 8 EMA")
    if blocked:
        print(f"  Watching: {', '.join(r.ticker for r in blocked)} "
              f"(1W fanning, 4H not ready)")
    print(f"{'─'*55}\n")


if __name__ == "__main__":
    from signal_checker import run_full_checklist

    ACCOUNT = float(input("Account balance ($): ") if len(sys.argv) < 2 else sys.argv[1])

    print("Fetching 1W data (weekly bias gate)...")
    weekly_data    = fetch_all_assets(timeframe="1w")
    weekly_results = run_full_checklist(weekly_data, timeframe="1w")

    entries = find_4h_entries(
        weekly_results,
        account_balance=ACCOUNT,
        risk_pct=1.0,
    )

    if not any(e.signal_4h.passed for e in entries):
        print("No 4H entries right now. Check again at next 4H close.")
