"""
tradingview_mcp.py — Live chart data layer for the trading agent.

TradingView does not expose a public MCP server, so this module
replicates the data TradingView would show using Kraken (geo-free)
as the source. Output format mirrors TradingView's pine_script indicator
naming so the agent can reference the same field names across both tools.

Usage:
    python3 tradingview_mcp.py                  # print chart summary for all assets
    python3 tradingview_mcp.py --asset BTC      # single asset
    python3 tradingview_mcp.py --timeframe 4h   # specific timeframe

What it provides:
  - Live OHLCV candles (Kraken public API)
  - EMA 8 / 20 / 50 (named "ema_8", "ema_20", "ema_50" — TV convention)
  - ATR(7) dynamic stop distance
  - RSI(14) momentum filter
  - VWAP (session-level, resets daily)
  - Trend bias label per rules.md §1
  - Support / resistance levels (recent highs/lows)
  - Signal readiness status per Cockpit Checklist

Data source: Kraken via ccxt (no key, no geo-block)
Update frequency: on-demand (call fetch_chart_data() to refresh)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data_fetcher import (
    fetch_ohlcv,
    add_ema,
    add_atr,
    classify_ema_trend,
    check_body_rule,
    get_exchange,
    WATCH_LIST,
)

VAULT_ROOT = Path(__file__).parent.parent


# ── Technical indicator additions ─────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """RSI(14) momentum filter."""
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, float("inf"))
    df["rsi_14"] = 100 - (100 / (1 + rs))
    return df


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Session VWAP — resets at midnight UTC (matches TradingView default)."""
    df = df.copy()
    df["date"] = df.index.date if hasattr(df.index, "date") else [t.date() for t in df.index]
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["tp_vol"] = typical * df["volume"]
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["cum_tp_vol"] = df.groupby("date")["tp_vol"].cumsum()
    df["vwap"] = df["cum_tp_vol"] / df["cum_vol"].replace(0, float("nan"))
    df.drop(columns=["date", "tp_vol", "cum_vol", "cum_tp_vol"], inplace=True)
    return df


def find_levels(df: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    """Recent swing high and swing low (support / resistance)."""
    recent = df.iloc[-lookback:]
    return float(recent["high"].max()), float(recent["low"].min())


# ── Chart data container ───────────────────────────────────────────────────────

@dataclass
class ChartSnapshot:
    """All indicator values for one asset at one timeframe — same naming as TradingView."""
    ticker:      str
    timeframe:   str
    timestamp:   datetime

    # Price
    open:        float
    high:        float
    low:         float
    close:       float
    volume:      float

    # Trend (rules.md §1)
    ema_8:       float
    ema_20:      float
    ema_50:      float
    ema_trend:   str          # FANNING-BULL | FANNING-BEAR | CONVERGING | FLAT

    # Risk (rules.md §4)
    atr_7:       float
    stop_long:   float        # close - atr_7
    stop_short:  float        # close + atr_7

    # Momentum
    rsi_14:      float
    vwap:        float

    # Price structure
    resistance:  float        # 20-bar swing high
    support:     float        # 20-bar swing low

    # Signal readiness
    body_rule:   bool
    signal_ready: bool        # True only if EMA fan + body rule + price at 8 EMA

    # Raw DataFrame (for downstream callers)
    df:          pd.DataFrame = field(repr=False)


def fetch_chart_data(
    ticker: str,
    timeframe: str = "1w",
    limit: int = 100,
) -> ChartSnapshot:
    """
    Fetch and compute all chart indicators for one asset.
    Equivalent to opening a TradingView chart at this timeframe.
    """
    symbol   = WATCH_LIST.get(ticker)
    if not symbol:
        raise ValueError(f"Unknown ticker: {ticker}. Valid: {list(WATCH_LIST)}")

    exchange = get_exchange()
    df       = fetch_ohlcv(exchange, symbol, timeframe, limit=limit)
    df       = add_ema(df)
    df       = add_atr(df)
    df       = add_rsi(df)
    try:
        df   = add_vwap(df)
        vwap_val = float(df["vwap"].iloc[-1])
    except Exception:
        vwap_val = float("nan")

    latest    = df.iloc[-1]
    trend     = classify_ema_trend(latest)

    if trend == "FANNING-BULL":
        body_ok = check_body_rule(latest, "bullish")
    elif trend == "FANNING-BEAR":
        body_ok = check_body_rule(latest, "bearish")
    else:
        body_ok = False

    # Signal ready: EMA fanning + body rule + price within 1 ATR of 8 EMA
    at_8ema    = abs(latest["close"] - latest["ema_8"]) <= latest["atr_7"]
    signal_rdy = trend in ("FANNING-BULL", "FANNING-BEAR") and body_ok and at_8ema

    resistance, support = find_levels(df)

    return ChartSnapshot(
        ticker    = ticker,
        timeframe = timeframe,
        timestamp = df.index[-1].to_pydatetime(),
        open      = float(latest["open"]),
        high      = float(latest["high"]),
        low       = float(latest["low"]),
        close     = float(latest["close"]),
        volume    = float(latest["volume"]),
        ema_8     = float(latest["ema_8"]),
        ema_20    = float(latest["ema_20"]),
        ema_50    = float(latest["ema_50"]),
        ema_trend = trend,
        atr_7     = float(latest["atr_7"]),
        stop_long = float(latest["close"] - latest["atr_7"]),
        stop_short= float(latest["close"] + latest["atr_7"]),
        rsi_14    = float(latest["rsi_14"]),
        vwap      = vwap_val,
        resistance= resistance,
        support   = support,
        body_rule = body_ok,
        signal_ready = signal_rdy,
        df        = df,
    )


def fetch_all_charts(timeframe: str = "1w") -> dict[str, ChartSnapshot]:
    """Fetch chart snapshots for all watch-list assets."""
    snapshots: dict[str, ChartSnapshot] = {}
    for ticker in WATCH_LIST:
        try:
            snapshots[ticker] = fetch_chart_data(ticker, timeframe=timeframe)
        except Exception as e:
            print(f"  {ticker}: chart fetch failed — {e}")
    return snapshots


# ── Console display ────────────────────────────────────────────────────────────

def print_chart_summary(snap: ChartSnapshot) -> None:
    rsi_note = ""
    if snap.rsi_14 > 70:
        rsi_note = " ⚠ OVERBOUGHT"
    elif snap.rsi_14 < 30:
        rsi_note = " ⚠ OVERSOLD"

    ready_tag = "✓ READY" if snap.signal_ready else "— waiting"

    print(f"\n{'─'*62}")
    print(f"  {snap.ticker}  [{snap.timeframe.upper()}]  {snap.timestamp.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'─'*62}")
    print(f"  Price:       O:{snap.open:.6g}  H:{snap.high:.6g}  "
          f"L:{snap.low:.6g}  C:{snap.close:.6g}")
    print(f"  EMA 8/20/50: {snap.ema_8:.6g} / {snap.ema_20:.6g} / {snap.ema_50:.6g}")
    print(f"  Trend:       {snap.ema_trend:<16}  Body: {'PASS' if snap.body_rule else 'FAIL'}")
    print(f"  ATR(7):      {snap.atr_7:.6g}  |  Stop↑ {snap.stop_short:.6g}  Stop↓ {snap.stop_long:.6g}")
    print(f"  RSI(14):     {snap.rsi_14:.1f}{rsi_note}")
    print(f"  VWAP:        {snap.vwap:.6g}" if not __import__('math').isnan(snap.vwap) else "  VWAP:        N/A (weekly data)")
    print(f"  S/R:         Support {snap.support:.6g}  |  Resistance {snap.resistance:.6g}")
    print(f"  Signal:      {ready_tag}")


def print_full_report(timeframe: str = "1w") -> None:
    print(f"\n{'='*62}")
    print(f"  CHART DATA — {timeframe.upper()} Timeframe  (Kraken/TradingView parity)")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*62}")

    snapshots = fetch_all_charts(timeframe)

    ready_assets  = [t for t, s in snapshots.items() if s.signal_ready]
    fanning_count = sum(1 for s in snapshots.values() if "FANNING" in s.ema_trend)

    for snap in snapshots.values():
        print_chart_summary(snap)

    print(f"\n{'='*62}")
    print(f"  SUMMARY")
    print(f"{'─'*62}")
    print(f"  Fanning assets:  {fanning_count}/{len(snapshots)}")
    if ready_assets:
        print(f"  SIGNAL READY:    {', '.join(ready_assets)}")
    else:
        print(f"  Signal ready:    None — wait for pullback to 8 EMA")
    print(f"{'='*62}\n")


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="TradingVault Chart Data Layer")
    parser.add_argument("--asset",     default=None,  help="Single asset (e.g. BTC)")
    parser.add_argument("--timeframe", default="1w",  help="Timeframe (1w/4h/1d/1h)")
    args = parser.parse_args()

    if args.asset:
        snap = fetch_chart_data(args.asset.upper(), timeframe=args.timeframe)
        print_chart_summary(snap)
    else:
        print_full_report(timeframe=args.timeframe)
