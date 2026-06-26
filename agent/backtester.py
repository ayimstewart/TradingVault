"""
backtester.py — Walk-forward backtest of Cockpit Checklist signals on historical OHLCV.

Reuses signal_checker.check_signal on each bar (no lookahead on indicators).
Simulates ATR(7) stop and 1:1 target per rules.md §4.

Run:  python3 backtester.py
      python3 backtester.py --timeframe 4h --limit 500
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import pandas as pd

from data_fetcher import (
    WATCH_LIST,
    add_atr,
    add_ema,
    fetch_ohlcv,
    get_exchange,
    normalize_timeframe,
)
from signal_checker import SignalResult, SignalType, check_signal

VAULT_ROOT = Path(__file__).parent.parent
SOURCES_DIR = VAULT_ROOT / "sources"
SOURCES_DIR.mkdir(exist_ok=True)

# EMA(50) needs 50 bars; extra buffer for stable ATR(7)
MIN_WARMUP = 55
DEFAULT_LIMIT = 200
RISK_PCT_PER_TRADE = 1.0   # 1% capital risked per 1R (90-90-90 aligned reporting)


class TradeOutcome(Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    OPEN = "OPEN"       # Still unresolved at end of data
    EXPIRED = "EXPIRED"


@dataclass
class BacktestTrade:
    ticker: str
    timeframe: str
    entry_time: pd.Timestamp
    signal_type: SignalType
    entry_price: float
    stop_loss: float
    target_1r: float
    exit_time: pd.Timestamp | None = None
    exit_price: float = 0.0
    outcome: TradeOutcome = TradeOutcome.OPEN
    r_multiple: float = 0.0
    ema_trend: str = ""

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry_price - self.stop_loss)


@dataclass
class BacktestSummary:
    ticker: str
    timeframe: str
    total_bars: int
    signals: int
    wins: int
    losses: int
    open_trades: int
    win_rate: float
    total_r: float
    avg_r: float
    max_drawdown_r: float
    final_capital_pct: float
    trades: list[BacktestTrade] = field(default_factory=list)


def prepare_data(
    ticker: str,
    timeframe: str = "1w",
    limit: int = DEFAULT_LIMIT,
) -> pd.DataFrame:
    """Fetch OHLCV and attach indicators for one asset."""
    exchange = get_exchange()
    symbol = WATCH_LIST[ticker]
    df = fetch_ohlcv(exchange, symbol, timeframe, limit=limit)
    df = add_ema(df)
    df = add_atr(df)
    return df


def simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
    signal: SignalResult,
) -> BacktestTrade:
    """
    Enter at signal bar close; resolve on subsequent bars via high/low.
    Conservative rule: if stop and target both touched same bar → stop first.
    """
    entry_row = df.iloc[entry_idx]
    trade = BacktestTrade(
        ticker=signal.ticker,
        timeframe=signal.timeframe,
        entry_time=df.index[entry_idx],
        signal_type=signal.signal_type,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target_1r=signal.target_1r,
        ema_trend=signal.ema_trend,
    )

    risk = trade.risk_per_unit
    if risk == 0:
        trade.outcome = TradeOutcome.EXPIRED
        return trade

    for j in range(entry_idx + 1, len(df)):
        bar = df.iloc[j]

        if signal.signal_type == SignalType.LONG:
            stopped = bar["low"] <= signal.stop_loss
            target_hit = bar["high"] >= signal.target_1r
            if stopped:
                trade.exit_time = df.index[j]
                trade.exit_price = signal.stop_loss
                trade.outcome = TradeOutcome.LOSS
                trade.r_multiple = -1.0
                return trade
            if target_hit:
                trade.exit_time = df.index[j]
                trade.exit_price = signal.target_1r
                trade.outcome = TradeOutcome.WIN
                trade.r_multiple = 1.0
                return trade

        elif signal.signal_type == SignalType.SHORT:
            stopped = bar["high"] >= signal.stop_loss
            target_hit = bar["low"] <= signal.target_1r
            if stopped:
                trade.exit_time = df.index[j]
                trade.exit_price = signal.stop_loss
                trade.outcome = TradeOutcome.LOSS
                trade.r_multiple = -1.0
                return trade
            if target_hit:
                trade.exit_time = df.index[j]
                trade.exit_price = signal.target_1r
                trade.outcome = TradeOutcome.WIN
                trade.r_multiple = 1.0
                return trade

    trade.outcome = TradeOutcome.OPEN
    trade.exit_price = df.iloc[-1]["close"]
    return trade


def backtest_asset(
    df: pd.DataFrame,
    ticker: str,
    timeframe: str = "1w",
    capital_pct: float = 100.0,
) -> BacktestSummary:
    """
    Walk-forward: at each bar after warmup, run checklist on history-to-date.
    One trade at a time — no overlapping positions on same asset.
    """
    trades: list[BacktestTrade] = []
    in_trade_until = MIN_WARMUP - 1

    for i in range(MIN_WARMUP, len(df)):
        if i <= in_trade_until:
            continue

        window = df.iloc[: i + 1].copy()
        signal = check_signal(window, ticker, timeframe, capital_pct)

        if not signal.passed:
            continue

        trade = simulate_trade(df, i, signal)
        trades.append(trade)

        if trade.exit_time is not None:
            # Jump to bar after exit
            exit_idx = df.index.get_loc(trade.exit_time)
            in_trade_until = exit_idx
        else:
            # Unresolved — stop scanning
            break

    wins = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
    losses = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
    open_trades = sum(1 for t in trades if t.outcome == TradeOutcome.OPEN)
    closed = wins + losses

    total_r = sum(t.r_multiple for t in trades if t.outcome in (TradeOutcome.WIN, TradeOutcome.LOSS))
    avg_r = total_r / closed if closed else 0.0
    win_rate = (wins / closed * 100) if closed else 0.0

    # Drawdown in R and capital simulation (1% risk per R)
    equity_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    capital = 100.0

    for t in trades:
        if t.outcome == TradeOutcome.WIN:
            equity_r += 1.0
            capital *= 1 + RISK_PCT_PER_TRADE / 100
        elif t.outcome == TradeOutcome.LOSS:
            equity_r -= 1.0
            capital *= 1 - RISK_PCT_PER_TRADE / 100
        peak_r = max(peak_r, equity_r)
        max_dd_r = max(max_dd_r, peak_r - equity_r)

    return BacktestSummary(
        ticker=ticker,
        timeframe=timeframe,
        total_bars=len(df),
        signals=len(trades),
        wins=wins,
        losses=losses,
        open_trades=open_trades,
        win_rate=win_rate,
        total_r=total_r,
        avg_r=avg_r,
        max_drawdown_r=max_dd_r,
        final_capital_pct=capital,
        trades=trades,
    )


def backtest_watch_list(
    timeframe: str = "1w",
    limit: int = DEFAULT_LIMIT,
    tickers: list[str] | None = None,
) -> list[BacktestSummary]:
    """Run backtest on all (or selected) watch list assets."""
    timeframe = normalize_timeframe(timeframe)
    tickers = tickers or list(WATCH_LIST.keys())
    summaries: list[BacktestSummary] = []

    print(f"\n{'='*55}")
    print(f"  BACKTEST — {timeframe.upper()} | {limit} bars | Cockpit Checklist")
    print(f"  Entry: close | Stop: ATR(7) | Target: 1:1 R")
    print(f"{'='*55}")

    for ticker in tickers:
        try:
            df = prepare_data(ticker, timeframe, limit)
            summary = backtest_asset(df, ticker, timeframe)
            summaries.append(summary)

            print(f"\n  {ticker:<5} | Signals: {summary.signals:>3} | "
                  f"W/L: {summary.wins}/{summary.losses} | "
                  f"Win%: {summary.win_rate:>5.1f} | "
                  f"Total R: {summary.total_r:>+6.1f} | "
                  f"Capital: {summary.final_capital_pct:.1f}%")

            for t in summary.trades:
                exit_str = t.exit_time.strftime("%Y-%m-%d") if t.exit_time else "open"
                print(f"    {t.entry_time.strftime('%Y-%m-%d')} {t.signal_type.value:<5} "
                      f"{t.outcome.value:<5} R={t.r_multiple:+.1f} exit={exit_str}")

        except Exception as e:
            print(f"  {ticker:<5} | ERROR: {e}")

    return summaries


def save_backtest_report(
    summaries: list[BacktestSummary],
    timeframe: str,
) -> Path:
    """Write backtest results to sources/ for NotebookLM ingestion."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = SOURCES_DIR / f"{today}-backtest-{timeframe}.md"

    lines = [
        f"# Backtest Report — {today}",
        "",
        f"> Timeframe: **{timeframe.upper()}** | Strategy: Cockpit Checklist (TCL)",
        f"> Rules: EMA fan + 30% body + price at 8 EMA + ATR(7) stop + 1:1 target",
        "",
        "## Summary",
        "",
        "| Asset | Signals | Wins | Losses | Win% | Total R | Max DD (R) | Final Capital % |",
        "|-------|---------|------|--------|------|---------|------------|-----------------|",
    ]

    for s in summaries:
        lines.append(
            f"| {s.ticker} | {s.signals} | {s.wins} | {s.losses} | "
            f"{s.win_rate:.1f} | {s.total_r:+.1f} | {s.max_drawdown_r:.1f} | "
            f"{s.final_capital_pct:.1f} |"
        )

    total_signals = sum(s.signals for s in summaries)
    total_wins = sum(s.wins for s in summaries)
    total_losses = sum(s.losses for s in summaries)
    closed = total_wins + total_losses
    agg_win_rate = (total_wins / closed * 100) if closed else 0.0
    agg_r = sum(s.total_r for s in summaries)

    lines += [
        "",
        "## Aggregate",
        f"- Total signals: {total_signals}",
        f"- Win rate: {agg_win_rate:.1f}%",
        f"- Combined R: {agg_r:+.1f}",
        "",
        "## Methodology",
        "- Walk-forward: indicators computed only on data available at each bar",
        "- One open trade per asset at a time",
        "- Same-bar stop+target: stop assumed first (capital conservation)",
        f"- Capital model: {RISK_PCT_PER_TRADE}% risk per 1R",
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
    ]

    output_path.write_text("\n".join(lines))
    print(f"\n✓ Backtest report saved → {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Backtest Cockpit Checklist signals")
    parser.add_argument("--timeframe", default="1w", help="ccxt timeframe (default: 1w)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="OHLCV bars to fetch")
    parser.add_argument("--ticker", help="Single ticker only (e.g. BTC)")
    args = parser.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else None
    summaries = backtest_watch_list(
        timeframe=args.timeframe,
        limit=args.limit,
        tickers=tickers,
    )

    if summaries:
        save_backtest_report(summaries, normalize_timeframe(args.timeframe))

    print(f"\n{'─'*55}")
    print("  Backtest complete. Review sources/ report for NotebookLM import.")
    print(f"{'─'*55}\n")


if __name__ == "__main__":
    main()
