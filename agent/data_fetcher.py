"""
data_fetcher.py — OHLCV data fetcher for the trading agent watch list.

Pulls candlestick data for: BTC, ETH, SOL, XRP, LINK, PEPE
Uses Kraken via ccxt — free public data, no API key, no geo-restrictions.

Binance blocks US/restricted locations (error 451).
Kraken works globally with no sign-up required for public market data.

Install: pip3 install ccxt pandas
Run:     python3 data_fetcher.py
"""

import ccxt
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

# ── Watch list — Kraken uses USD pairs ────────────────────────────────────
WATCH_LIST = {
    "BTC":  "BTC/USD",
    "ETH":  "ETH/USD",
    "SOL":  "SOL/USD",
    "XRP":  "XRP/USD",
    "LINK": "LINK/USD",
    "PEPE": "PEPE/USD",
}

# ── Timeframes (ccxt/Kraken format — lowercase required) ───────────────────
# Weekly bias FIRST — rules.md is non-negotiable on this
TIMEFRAMES = {
    "1w": "1w",   # Primary bias — assessed before anything else
    "1d": "1d",   # Daily confirmation
    "4h": "4h",   # Entry timeframe
    "1h": "1h",   # Fine-tuning (optional)
}

# Aliases for human-readable labels (TradingView uses 1W; ccxt uses 1w)
TIMEFRAME_ALIASES = {
    "1W": "1w",
    "1D": "1d",
    "4H": "4h",
    "1H": "1h",
}


def normalize_timeframe(timeframe: str) -> str:
    """Map display labels (1W) to ccxt-native strings (1w)."""
    return TIMEFRAME_ALIASES.get(timeframe, timeframe)

CANDLES_TO_FETCH = 100   # Enough history for EMA(50) + ATR(7) + pattern work

# ── Output path (lands in sources/ for NotebookLM ingestion) ──────────────
VAULT_ROOT = Path(__file__).parent.parent
SOURCES_DIR = VAULT_ROOT / "sources"
SOURCES_DIR.mkdir(exist_ok=True)


def get_exchange() -> ccxt.Exchange:
    """
    Return Kraken exchange instance — public data, no API key needed.
    No geo-restrictions. Works from US and everywhere else.
    """
    return ccxt.kraken({"enableRateLimit": True})


def fetch_ohlcv(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    limit: int = CANDLES_TO_FETCH,
) -> pd.DataFrame:
    """Fetch OHLCV candles and return as a clean DataFrame."""
    timeframe = normalize_timeframe(timeframe)
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index()
    return df


def add_ema(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA 8, 20, 50 — required by Cockpit Checklist trend filter."""
    df["ema_8"]  = df["close"].ewm(span=8,  adjust=False).mean()
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    return df


def add_atr(df: pd.DataFrame, period: int = 7) -> pd.DataFrame:
    """Add ATR(7) — required for dynamic stop-loss by rules.md."""
    high_low   = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close  = (df["low"]  - df["close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df[f"atr_{period}"] = true_range.ewm(span=period, adjust=False).mean()
    return df


def classify_ema_trend(row: pd.Series) -> str:
    """
    Classify EMA fan status per rules.md Cockpit Checklist.
    Returns: FANNING-BULL | FANNING-BEAR | CONVERGING | FLAT
    """
    e8, e20, e50 = row["ema_8"], row["ema_20"], row["ema_50"]
    if e8 > e20 > e50:
        return "FANNING-BULL"
    if e8 < e20 < e50:
        return "FANNING-BEAR"
    spread = abs(e8 - e50) / e50 * 100
    return "FLAT" if spread < 0.5 else "CONVERGING"


def check_body_rule(row: pd.Series, direction: str) -> bool:
    """
    Validate the 30% Body Rule from rules.md §2.
    direction: 'bullish' or 'bearish'
    """
    candle_range = row["high"] - row["low"]
    if candle_range == 0:
        return False
    if direction == "bullish":
        threshold = row["high"] - (candle_range * 0.30)
        return row["close"] >= threshold
    if direction == "bearish":
        threshold = row["low"] + (candle_range * 0.30)
        return row["close"] <= threshold
    return False


def fetch_all_assets(timeframe: str = "1w") -> dict:
    """Fetch OHLCV + indicators for all watch list assets at a given timeframe."""
    exchange = get_exchange()
    results  = {}

    print(f"\n{'─'*50}")
    print(f"Fetching {timeframe.upper()} data for watch list...")
    print(f"{'─'*50}")

    for ticker, symbol in WATCH_LIST.items():
        try:
            df = fetch_ohlcv(exchange, symbol, timeframe)
            df = add_ema(df)
            df = add_atr(df)

            latest = df.iloc[-1]
            trend  = classify_ema_trend(latest)

            if trend == "FANNING-BULL":
                body_valid = check_body_rule(latest, "bullish")
            elif trend == "FANNING-BEAR":
                body_valid = check_body_rule(latest, "bearish")
            else:
                body_valid = False

            results[ticker] = df

            print(f"  {ticker:<5} | Close: {latest['close']:>12.8g} | "
                  f"ATR(7): {latest['atr_7']:>10.4f} | "
                  f"Trend: {trend:<14} | Body: {'PASS' if body_valid else 'FAIL'}")

        except Exception as e:
            print(f"  {ticker:<5} | ERROR: {e}")

    return results


def save_morning_brief(data: dict) -> Path:
    """Write Morning Brief to sources/ for NotebookLM ingestion."""
    today       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = SOURCES_DIR / f"{today}-morning-brief.md"

    lines = [
        f"# Morning Brief — {today}",
        "",
        "> Auto-generated by data_fetcher.py",
        "",
        "## Watch List — Weekly (1W) Bias",
        "",
        "| Asset | Close | EMA 8 | EMA 20 | EMA 50 | ATR(7) | Trend | Body Rule |",
        "|-------|-------|-------|--------|--------|--------|-------|-----------|",
    ]

    for ticker, info in data.items():
        df    = info["df"]
        row   = df.iloc[-1]
        trend = classify_ema_trend(row)

        if trend == "FANNING-BULL":
            body = "PASS" if check_body_rule(row, "bullish") else "FAIL"
        elif trend == "FANNING-BEAR":
            body = "PASS" if check_body_rule(row, "bearish") else "FAIL"
        else:
            body = "N/A"

        lines.append(
            f"| {ticker} | {row['close']:.4f} | {row['ema_8']:.4f} | "
            f"{row['ema_20']:.4f} | {row['ema_50']:.4f} | "
            f"{row['atr_7']:.4f} | {trend} | {body} |"
        )

    lines += [
        "",
        "## Key",
        "- FANNING-BULL = 8 EMA > 20 EMA > 50 EMA → valid long setups only",
        "- FANNING-BEAR = 8 EMA < 20 EMA < 50 EMA → valid short setups only",
        "- CONVERGING / FLAT = NO TRADE (rules.md §1)",
        "- Body Rule: close must be in upper 30% (bull) or lower 30% (bear)",
        "- ATR(7) = dynamic stop-loss distance (rules.md §4)",
        "",
        f"*Generated: {datetime.now(timezone.utc).isoformat()}*",
    ]

    output_path.write_text("\n".join(lines))
    print(f"\n✓ Morning Brief saved → {output_path}")
    print(f"  Next: notebooklm source add {output_path}")
    return output_path


def run_morning_brief():
    """Standalone run — fetch all assets and save brief."""
    print("\n" + "="*50)
    print("  TRADING AGENT — MORNING BRIEF")
    print("  Exchange: Kraken (no geo-restrictions)")
    print("="*50)

    weekly_data = fetch_all_assets(timeframe="1w")
    brief_data  = {ticker: {"df": df} for ticker, df in weekly_data.items()}
    brief_path  = save_morning_brief(brief_data)

    print("\nPRIORITY ASSETS (clean EMA fan):")
    priority = [
        (t, classify_ema_trend(df.iloc[-1]))
        for t, df in weekly_data.items()
        if classify_ema_trend(df.iloc[-1]) in ("FANNING-BULL", "FANNING-BEAR")
    ]
    if priority:
        for ticker, trend in priority:
            print(f"  → {ticker}: {trend}")
    else:
        print("  → No clean setups. Wait for trend to establish.")


if __name__ == "__main__":
    run_morning_brief()
