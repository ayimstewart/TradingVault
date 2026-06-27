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


def candle_color(row: pd.Series) -> str:
    """Return GREEN or RED for a single OHLCV row."""
    return "GREEN" if row["close"] >= row["open"] else "RED"


def compute_daily_structure(df_1d: pd.DataFrame) -> dict:
    """
    Advanced Market Structure — daily bias + anchor (rules.md §8).

    prev_day_bias: BUY if previous completed day green, SELL if red
    daily_open:    today's daily candle open (session anchor)
    """
    if len(df_1d) < 2:
        return {
            "prev_day_bias":  "UNKNOWN",
            "prev_day_color": "UNKNOWN",
            "daily_open":     float(df_1d.iloc[-1]["open"]) if len(df_1d) else 0.0,
        }

    prev_day = df_1d.iloc[-2]
    today    = df_1d.iloc[-1]
    color    = candle_color(prev_day)
    bias     = "BUY" if color == "GREEN" else "SELL"

    return {
        "prev_day_bias":  bias,
        "prev_day_color": color,
        "daily_open":     float(today["open"]),
    }


def classify_ams_bias(ema_trend: str, prev_day_bias: str) -> str:
    """Combined 1W + daily bias label for morning brief."""
    if prev_day_bias not in ("BUY", "SELL"):
        return "UNKNOWN"
    if ema_trend == "FANNING-BULL" and prev_day_bias == "BUY":
        return "BUY-ALIGNED"
    if ema_trend == "FANNING-BEAR" and prev_day_bias == "SELL":
        return "SELL-ALIGNED"
    if ema_trend in ("FANNING-BULL", "FANNING-BEAR"):
        return "CONFLICT-WAIT"
    return "NEUTRAL"


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
    Both open AND close must be in the upper/lower 30% zone.
    direction: 'bullish' or 'bearish'
    """
    candle_range = row["high"] - row["low"]
    if candle_range == 0:
        return False
    if direction == "bullish":
        threshold = row["high"] - (candle_range * 0.30)
        return row["open"] >= threshold and row["close"] >= threshold
    if direction == "bearish":
        threshold = row["low"] + (candle_range * 0.30)
        return row["open"] <= threshold and row["close"] <= threshold
    return False


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    ruflo-market-data OHLCV normalization (relative scaling).
    Adds norm_ columns — used for pattern vectorization and anomaly scoring.
    """
    df = df.copy()
    prev_close = df["close"].shift(1)
    df["norm_open"]  = (df["open"]  - prev_close) / prev_close.replace(0, float("nan"))
    df["norm_high"]  = (df["high"]  - df["open"]) / df["open"].replace(0, float("nan"))
    df["norm_low"]   = (df["low"]   - df["open"]) / df["open"].replace(0, float("nan"))
    df["norm_close"] = (df["close"] - df["open"]) / df["open"].replace(0, float("nan"))
    vol_mean = df["volume"].rolling(20, min_periods=1).mean()
    vol_std  = df["volume"].rolling(20, min_periods=1).std().replace(0, 1)
    df["norm_volume"] = (df["volume"] - vol_mean) / vol_std
    return df


def detect_candlestick_patterns(df: pd.DataFrame) -> dict:
    """
    ruflo-market-data pattern library — single and multi-candle formations.
    Returns dict of pattern_name → {"detected": bool, "reliability": str}
    """
    if len(df) < 2:
        return {}

    row  = df.iloc[-1]
    prev = df.iloc[-2]

    candle_range = row["high"] - row["low"]
    body         = abs(row["close"] - row["open"])
    upper_wick   = row["high"] - max(row["close"], row["open"])
    lower_wick   = min(row["close"], row["open"]) - row["low"]

    patterns = {}

    if candle_range > 0:
        # Doji: body < 10% of full range
        patterns["doji"] = {
            "detected":    body / candle_range < 0.10,
            "reliability": "Medium",
        }
        # Hammer: small body in upper zone, long lower wick ≥ 2× body
        hammer_top = row["high"] - (candle_range * 0.30)
        patterns["hammer"] = {
            "detected": (
                min(row["close"], row["open"]) >= hammer_top
                and lower_wick >= 2 * max(body, 1e-10)
                and upper_wick <= body * 0.5
            ),
            "reliability": "Medium-High",
        }
        # Shooting star: small body in lower zone, long upper wick ≥ 2× body
        shoot_bot = row["low"] + (candle_range * 0.30)
        patterns["shooting_star"] = {
            "detected": (
                max(row["close"], row["open"]) <= shoot_bot
                and upper_wick >= 2 * max(body, 1e-10)
                and lower_wick <= body * 0.5
            ),
            "reliability": "Medium-High",
        }

    # Engulfing (2-candle): current body fully engulfs previous body
    prev_body_hi = max(prev["close"], prev["open"])
    prev_body_lo = min(prev["close"], prev["open"])
    curr_body_hi = max(row["close"],  row["open"])
    curr_body_lo = min(row["close"],  row["open"])

    patterns["bullish_engulfing"] = {
        "detected": (
            prev["close"] < prev["open"]
            and row["close"] > row["open"]
            and curr_body_lo < prev_body_lo
            and curr_body_hi > prev_body_hi
        ),
        "reliability": "High",
    }
    patterns["bearish_engulfing"] = {
        "detected": (
            prev["close"] > prev["open"]
            and row["close"] < row["open"]
            and curr_body_lo < prev_body_lo
            and curr_body_hi > prev_body_hi
        ),
        "reliability": "High",
    }

    return patterns


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
            df = normalize_ohlcv(df)   # ruflo-market-data: relative normalization

            latest = df.iloc[-1]
            trend  = classify_ema_trend(latest)

            if trend == "FANNING-BULL":
                body_valid = check_body_rule(latest, "bullish")
            elif trend == "FANNING-BEAR":
                body_valid = check_body_rule(latest, "bearish")
            else:
                body_valid = False

            # ruflo-market-data: pattern detection
            patterns = detect_candlestick_patterns(df)
            active_patterns = [
                f"{name}({p['reliability']})"
                for name, p in patterns.items()
                if p["detected"]
            ]

            results[ticker] = df

            pattern_str = ", ".join(active_patterns) if active_patterns else "none"
            print(f"  {ticker:<5} | Close: {latest['close']:>12.8g} | "
                  f"ATR(7): {latest['atr_7']:>10.4f} | "
                  f"Trend: {trend:<14} | Body: {'PASS' if body_valid else 'FAIL'} | "
                  f"Patterns: {pattern_str}")

        except Exception as e:
            print(f"  {ticker:<5} | ERROR: {e}")

    return results


def fetch_market_structure() -> dict:
    """
    Fetch 1W + 1D + 1H for all watch-list assets.
    Adds AMS fields: prev_day_bias, prev_day_color, daily_open, combined_bias.
    """
    exchange = get_exchange()
    results  = {}

    print(f"\n{'─'*50}")
    print("Fetching market structure (1W + 1D + 1H)...")
    print(f"{'─'*50}")

    for ticker, symbol in WATCH_LIST.items():
        try:
            df_1w = fetch_ohlcv(exchange, symbol, "1w")
            df_1d = fetch_ohlcv(exchange, symbol, "1d")
            df_1h = fetch_ohlcv(exchange, symbol, "1h", limit=48)

            df_1w = add_ema(add_atr(normalize_ohlcv(df_1w)))
            df_1d = add_atr(df_1d)
            df_1h = add_atr(df_1h)

            daily = compute_daily_structure(df_1d)
            trend = classify_ema_trend(df_1w.iloc[-1])
            bias  = classify_ams_bias(trend, daily["prev_day_bias"])

            results[ticker] = {
                "df":             df_1w,
                "df_1d":          df_1d,
                "df_1h":          df_1h,
                "prev_day_bias":  daily["prev_day_bias"],
                "prev_day_color": daily["prev_day_color"],
                "daily_open":     daily["daily_open"],
                "combined_bias":  bias,
            }

            print(
                f"  {ticker:<5} | 1W: {trend:<14} | Prev: {daily['prev_day_color']:<5} "
                f"| Open: {daily['daily_open']:>12.8g} | Bias: {bias}"
            )
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
        "## Watch List — Weekly (1W) + Advanced Market Structure (§8)",
        "",
        "| Asset | 1W Trend | Prev Day | Daily Open | 1H Status | Bias | Body Rule |",
        "|-------|----------|----------|------------|-----------|------|-----------|",
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

        prev_day  = info.get("prev_day_color", "—")
        daily_open = info.get("daily_open", 0.0)
        h1_status = info.get("h1_status", "—")
        bias      = info.get("combined_bias", info.get("bias", "—"))

        open_str = f"{daily_open:.4g}" if daily_open else "—"
        lines.append(
            f"| {ticker} | {trend} | {prev_day} | {open_str} | {h1_status} | {bias} | {body} |"
        )

    lines += [
        "",
        "## Key",
        "- FANNING-BULL = 8 EMA > 20 EMA > 50 EMA → valid long setups only",
        "- FANNING-BEAR = 8 EMA < 20 EMA < 50 EMA → valid short setups only",
        "- CONVERGING / FLAT = NO TRADE (rules.md §1)",
        "- Prev Day GREEN = buy-only bias | RED = sell-only bias (rules.md §8)",
        "- Daily Open = session anchor price (rules.md §8)",
        "- 1H Status = pullback sequence state before entry (rules.md §8)",
        "- Bias = 1W trend aligned with daily bias (BUY-ALIGNED / CONFLICT-WAIT)",
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

    weekly_data = fetch_market_structure()
    brief_data  = {
        ticker: {
            "df":             info["df"],
            "prev_day_color": info["prev_day_color"],
            "daily_open":     info["daily_open"],
            "combined_bias":  info["combined_bias"],
            "h1_status":      info.get("h1_status", "—"),
        }
        for ticker, info in weekly_data.items()
    }
    brief_path  = save_morning_brief(brief_data)

    print("\nPRIORITY ASSETS (clean EMA fan):")
    priority = [
        (t, classify_ema_trend(info["df"].iloc[-1]))
        for t, info in weekly_data.items()
        if classify_ema_trend(info["df"].iloc[-1]) in ("FANNING-BULL", "FANNING-BEAR")
    ]
    if priority:
        for ticker, trend in priority:
            print(f"  → {ticker}: {trend}")
    else:
        print("  → No clean setups. Wait for trend to establish.")


if __name__ == "__main__":
    run_morning_brief()
