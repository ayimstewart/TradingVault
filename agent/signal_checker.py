"""
signal_checker.py — Validates trade setups against rules.md Cockpit Checklist.

This is the enforcement layer. No signal leaves this module without
passing every rule in rules.md. Period.

Run:  python signal_checker.py
Or import: from signal_checker import check_signal
"""

import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum
from typing import Optional


class SignalType(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    NONE  = "NONE"


class BlockReason(Enum):
    AMS_BIAS_CONFLICT    = "Daily bias conflicts with 1W trend — wait (rules.md §8)"
    AMS_DAILY_DIRECTION  = "Daily bias direction only — wrong side blocked (rules.md §8)"
    AMS_NO_1H_PULLBACK   = "1H pullback not complete — wait for counter-trend sequence (rules.md §8)"
    EMA_NOT_FANNING      = "EMA not fanning — trend invalid (rules.md §1)"
    BODY_RULE_FAILED     = "Candle body not in valid zone (rules.md §2)"
    NO_STOP_LOSS         = "No ATR(7) stop calculated (rules.md §4)"
    PRICE_NOT_AT_EMA     = "Price not at 8 EMA — wait for pullback"
    SILLY_DONATION_FOMO  = "FOMO detected — move already in progress (BLOCKED)"
    SILLY_DONATION_FORCE = "Forced setup — no valid confluence (BLOCKED)"
    CAPITAL_THRESHOLD    = "Capital below safe threshold — sizing reduced"


# ── ruflo-neural-trader: Market Regime ────────────────────────────────────────

class MarketRegime(Enum):
    """Matches ruflo-neural-trader RegimeVerdict.regime (pipeline-messages.ts)."""
    BULL_TRENDING   = "bull-trending"
    BEAR_TRENDING   = "bear-trending"
    RANGING         = "ranging"
    HIGH_VOLATILITY = "high-volatility"
    LOW_VOLATILITY  = "low-volatility"
    TRANSITIONING   = "transitioning"
    UNKNOWN         = "unknown"

    @property
    def display(self) -> str:
        return self.value.replace("-", " ").title()


@dataclass
class NeuralContext:
    """
    ruflo-neural-trader advisory context.
    NEVER overrides rules.md — informational weight layer only (same role as Kronos).
    """
    regime:           MarketRegime = MarketRegime.UNKNOWN
    anomaly_score:    float        = 0.0     # 0.0–1.0; >0.5 = significant
    anomaly_type:     str          = ""      # spike | drift | flatline | oscillation | pattern-break | cluster-outlier
    circuit_breakers: list         = field(default_factory=list)
    patterns:         list         = field(default_factory=list)
    regime_note:      str          = ""

    def to_console(self) -> str:
        lines = [f"  ── Neural Context (advisory — ruflo-neural-trader) ──"]
        lines.append(f"  Regime:      {self.regime.display} ({self.regime.value})  {self.regime_note}")
        if self.anomaly_score > 0.1:
            lines.append(f"  Anomaly:     {self.anomaly_score:.2f}  [{self.anomaly_type}]")
        if self.patterns:
            lines.append(f"  Patterns:    {', '.join(self.patterns)}")
        if self.circuit_breakers:
            for cb in self.circuit_breakers:
                lines.append(f"  ⚠ Breaker:  {cb}")
        return "\n".join(lines)


@dataclass
class SignalResult:
    """The output of every checklist validation. Every field must be filled."""
    ticker:        str
    timeframe:     str
    signal_type:   SignalType
    passed:        bool

    # Price levels (only populated if passed=True)
    entry_price:   float = 0.0
    stop_loss:     float = 0.0
    target_1r:     float = 0.0   # 1:1 Risk/Reward minimum

    # Checklist results
    ema_trend:     str   = ""
    body_rule:     bool  = False
    atr_value:     float = 0.0

    # Block reasons (populated if passed=False)
    blocked_by:    list[str] = field(default_factory=list)

    # ruflo-neural-trader advisory context (never blocks signals)
    neural_context: Optional[NeuralContext] = field(default=None)

    # Advanced Market Structure (rules.md §8)
    prev_day_bias:  str   = ""
    prev_day_color: str   = ""
    daily_open:     float = 0.0
    h1_status:      str   = ""
    combined_bias:  str   = ""

    # Non-blocking warnings (e.g. capital ORANGE — reduce sizing)
    flags:          list[str] = field(default_factory=list)

    # Execution routing: crypto | stocks | futures
    market_type:    str   = "crypto"

    # Metadata
    timestamp:     str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_log_row(self) -> str:
        """Format as a decisions-log.md table row."""
        result  = "✓ VALID" if self.passed else "✗ BLOCKED"
        reasons = "; ".join(self.blocked_by) if self.blocked_by else "—"
        return (
            f"| {self.timestamp[:10]} | {self.signal_type.value} | {self.ticker} | "
            f"{self.timeframe} | {self.ema_trend} | {result} | {reasons} | — | — |"
        )

    def to_console(self) -> str:
        lines = [
            f"\n{'═'*55}",
            f"  SIGNAL CHECK: {self.ticker} ({self.timeframe})",
            f"{'═'*55}",
            f"  EMA Trend:   {self.ema_trend}",
            f"  Body Rule:   {'PASS' if self.body_rule else 'FAIL'}",
            f"  ATR(7):      {self.atr_value:.4f}",
            f"  Signal:      {self.signal_type.value}",
            f"  Result:      {'✓ VALID — setup confirmed' if self.passed else '✗ BLOCKED'}",
        ]
        if self.prev_day_bias or self.daily_open:
            lines += [
                f"  ── Advanced Market Structure (§8) ──",
                f"  Prev Day:    {self.prev_day_color} → {self.prev_day_bias}",
                f"  Daily Open:  {self.daily_open:.4g}" if self.daily_open else "  Daily Open:  —",
                f"  1H Status:   {self.h1_status or '—'}",
                f"  Bias:        {self.combined_bias or '—'}",
            ]
        if self.passed:
            lines += [
                f"{'─'*55}",
                f"  Entry:       {self.entry_price:.4f}",
                f"  Stop Loss:   {self.stop_loss:.4f}  (ATR×1 below entry)",
                f"  Target 1R:   {self.target_1r:.4f}  (1:1 minimum)",
                f"  Risk/unit:   {abs(self.entry_price - self.stop_loss):.4f}",
            ]
        else:
            lines.append(f"{'─'*55}")
            for reason in self.blocked_by:
                lines.append(f"  ✗ {reason}")
        if self.neural_context is not None:
            lines.append(f"{'─'*55}")
            lines.append(self.neural_context.to_console())
        lines.append(f"{'═'*55}")
        return "\n".join(lines)


# ── ruflo-neural-trader: Regime / Anomaly / Circuit Breaker functions ─────────

def assess_regime(df: pd.DataFrame, row: pd.Series) -> tuple:
    """
    Local regime classifier aligned with ruflo-neural-trader RegimeVerdict schema.
    Plugin uses npx neural-trader --regime-detect; this Python layer mirrors the
    six regime slugs from pipeline-messages.ts for advisory context only.
    Returns (MarketRegime, note_str).
    """
    e8, e20, e50 = row["ema_8"], row["ema_20"], row["ema_50"]
    atr          = row.get("atr_7", 0.0)

    ema_spread_pct = abs(e8 - e50) / e50 * 100 if e50 > 0 else 0.0
    atr_series     = df["atr_7"].dropna()
    atr_mean       = atr_series.rolling(10, min_periods=1).mean().iloc[-1] if len(atr_series) else 0.0
    atr_ratio      = atr / atr_mean if atr_mean > 0 else 1.0

    if atr_ratio > 2.0:
        return MarketRegime.HIGH_VOLATILITY, "ATR >2× average — reduce size, widen stops"
    if atr_ratio < 0.5:
        return MarketRegime.LOW_VOLATILITY, "ATR <0.5× average — compression, breakout watch"

    fanning_bull = e8 > e20 > e50
    fanning_bear = e8 < e20 < e50

    if ema_spread_pct > 2.0 and fanning_bull:
        return MarketRegime.BULL_TRENDING, "Strong bull trend — momentum strategies aligned"
    if ema_spread_pct > 2.0 and fanning_bear:
        return MarketRegime.BEAR_TRENDING, "Strong bear trend — short momentum aligned"
    if ema_spread_pct < 0.5:
        return MarketRegime.RANGING, "EMAs flat — mean-reversion context, wait for breakout"
    if atr_ratio > 1.5:
        return MarketRegime.TRANSITIONING, "Regime change forming — wait for confirmation"

    return MarketRegime.UNKNOWN, ""


def calc_anomaly_score(df: pd.DataFrame, row: pd.Series) -> tuple:
    """
    ruflo-neural-trader Z-score composite: anomalyScore = min(1, meanZ / 3).
    Returns (score: float, type: str).
    """
    try:
        window = df.tail(20)
        fields = ["open", "high", "low", "close", "volume"]
        z_scores = []
        for f in fields:
            col = window[f]
            std = col.std()
            if std > 0:
                z_scores.append(abs((row[f] - col.mean()) / std))

        if not z_scores:
            return 0.0, ""

        mean_z = sum(z_scores) / len(z_scores)
        max_z  = max(z_scores)
        score  = min(1.0, mean_z / 3.0)

        if max_z > 5:
            atype = "spike"
        elif sum(1 for z in z_scores if z > 1) > len(z_scores) * 0.5:
            atype = "cluster-outlier"
        elif mean_z > 2:
            atype = "drift"
        elif score < 0.1:
            atype = "flatline"
        elif mean_z > 0.5 and max_z > 3:
            atype = "pattern-break"
        elif mean_z > 0.5:
            atype = "oscillation"
        else:
            atype = ""

        return score, atype

    except Exception:
        return 0.0, ""


def check_circuit_breakers(
    capital_pct:     float,
    daily_loss_pct:  float = 0.0,
    weekly_loss_pct: float = 0.0,
) -> list:
    """
    ruflo-neural-trader circuit breakers — active triggers returned as strings.
    These supplement the 90-90-90 capital safeguard in rules.md §5.
    """
    active = []
    if daily_loss_pct > 3.0:
        active.append(f"Daily loss {daily_loss_pct:.1f}% > 3% — halt new entries")
    if weekly_loss_pct > 5.0:
        active.append(f"Weekly loss {weekly_loss_pct:.1f}% > 5% — reduce sizes 50%")
    if capital_pct < 70:
        active.append("Capital <70% RED — no new signals until root cause audit")
    elif capital_pct < 80:
        active.append("Capital <80% ORANGE — reduce position sizing")
    elif capital_pct < 90:
        active.append("Capital <90% YELLOW — review last 3 decisions")
    return active


# ── Advanced Market Structure (rules.md §8) ───────────────────────────────────

def _is_green(row: pd.Series) -> bool:
    return row["close"] >= row["open"]


def _is_red(row: pd.Series) -> bool:
    return row["close"] < row["open"]


def detect_1h_pullback(df_1h: pd.DataFrame, daily_bias: str) -> dict:
    """
    1H pullback detector per rules.md §8.

    BUY bias  → red sequence, then first green candle = entry ready
    SELL bias → green sequence, then first red candle = entry ready
    """
    if df_1h is None or len(df_1h) < 2 or daily_bias not in ("BUY", "SELL"):
        return {
            "status":      "N/A",
            "entry_ready": False,
            "detail":      "Insufficient 1H data",
        }

    latest = df_1h.iloc[-1]
    counter_is_red = daily_bias == "BUY"

    if counter_is_red:
        entry_ready = _is_green(latest)
        if not entry_ready:
            # In or building counter-trend (red) sequence
            if _is_red(latest):
                return {
                    "status":      "IN-PULLBACK",
                    "entry_ready": False,
                    "detail":      "In red 1H sequence — wait for first green candle",
                }
            return {
                "status":      "NO-SEQUENCE",
                "entry_ready": False,
                "detail":      "No red counter-trend sequence yet",
            }
        # Latest green — count preceding red candles
        idx = len(df_1h) - 2
        red_count = 0
        while idx >= 0 and _is_red(df_1h.iloc[idx]):
            red_count += 1
            idx -= 1
        if red_count >= 1:
            return {
                "status":      "ENTRY-READY",
                "entry_ready": True,
                "detail":      f"First green after {red_count} red 1H candle(s)",
            }
        return {
            "status":      "NO-PULLBACK",
            "entry_ready": False,
            "detail":      "Green candle without prior red sequence",
        }

    # SELL bias — mirror logic
    entry_ready = _is_red(latest)
    if not entry_ready:
        if _is_green(latest):
            return {
                "status":      "IN-PULLBACK",
                "entry_ready": False,
                "detail":      "In green 1H sequence — wait for first red candle",
            }
        return {
            "status":      "NO-SEQUENCE",
            "entry_ready": False,
            "detail":      "No green counter-trend sequence yet",
        }

    idx = len(df_1h) - 2
    green_count = 0
    while idx >= 0 and _is_green(df_1h.iloc[idx]):
        green_count += 1
        idx -= 1
    if green_count >= 1:
        return {
            "status":      "ENTRY-READY",
            "entry_ready": True,
            "detail":      f"First red after {green_count} green 1H candle(s)",
        }
    return {
        "status":      "NO-PULLBACK",
        "entry_ready": False,
        "detail":      "Red candle without prior green sequence",
    }


def check_ams_gates(
    ema_trend: str,
    signal_type: SignalType,
    prev_day_bias: str,
    df_1h: pd.DataFrame | None = None,
) -> tuple[list[str], dict, str]:
    """
    Step 0 — Advanced Market Structure gates (rules.md §8).
    Returns (blocked_reasons, pullback_info, combined_bias).
    """
    blocked: list[str] = []
    from data_fetcher import classify_ams_bias

    combined_bias = classify_ams_bias(ema_trend, prev_day_bias)
    pullback = detect_1h_pullback(df_1h, prev_day_bias) if prev_day_bias in ("BUY", "SELL") else {
        "status": "N/A", "entry_ready": False, "detail": "No daily bias",
    }

    if prev_day_bias == "BUY" and signal_type == SignalType.SHORT:
        blocked.append(BlockReason.AMS_DAILY_DIRECTION.value)
    if prev_day_bias == "SELL" and signal_type == SignalType.LONG:
        blocked.append(BlockReason.AMS_DAILY_DIRECTION.value)

    if ema_trend == "FANNING-BULL" and prev_day_bias == "SELL":
        blocked.append(BlockReason.AMS_BIAS_CONFLICT.value)
    elif ema_trend == "FANNING-BEAR" and prev_day_bias == "BUY":
        blocked.append(BlockReason.AMS_BIAS_CONFLICT.value)

    if (
        combined_bias in ("BUY-ALIGNED", "SELL-ALIGNED")
        and signal_type != SignalType.NONE
        and not pullback["entry_ready"]
    ):
        blocked.append(
            f"{BlockReason.AMS_NO_1H_PULLBACK.value} ({pullback['status']}: {pullback['detail']})"
        )

    return blocked, pullback, combined_bias


def check_signal(
    df: pd.DataFrame,
    ticker: str,
    timeframe: str = "1w",
    capital_pct: float = 100.0,
    daily_loss_pct: float = 0.0,
    weekly_loss_pct: float = 0.0,
    *,
    df_1h: pd.DataFrame | None = None,
    prev_day_bias: str = "",
    prev_day_color: str = "",
    daily_open: float = 0.0,
) -> SignalResult:
    """
    Run the full Cockpit Checklist against the latest candle.

    Args:
        df:               DataFrame with columns: open, high, low, close,
                          ema_8, ema_20, ema_50, atr_7
                          (output of data_fetcher.add_ema + add_atr + normalize_ohlcv)
        ticker:           Asset name e.g. "BTC"
        timeframe:        Timeframe string e.g. "1w", "4h"
        capital_pct:      Current capital as % of starting capital (90-90-90 check)
        daily_loss_pct:   Session loss % today (for circuit breaker check)
        weekly_loss_pct:  Loss % this week (for circuit breaker check)

    Returns:
        SignalResult — fully populated, blocked or confirmed, with neural_context advisory.
    """
    row     = df.iloc[-1]
    prev    = df.iloc[-2] if len(df) > 1 else row
    blocked = []

    # ── Rule §1: EMA Fanning ───────────────────────────────────────────────
    e8, e20, e50 = row["ema_8"], row["ema_20"], row["ema_50"]

    if e8 > e20 > e50:
        ema_trend    = "FANNING-BULL"
        signal_type  = SignalType.LONG
    elif e8 < e20 < e50:
        ema_trend    = "FANNING-BEAR"
        signal_type  = SignalType.SHORT
    else:
        spread = abs(e8 - e50) / e50 * 100
        ema_trend   = "FLAT" if spread < 0.5 else "CONVERGING"
        signal_type = SignalType.NONE
        blocked.append(BlockReason.EMA_NOT_FANNING.value)

    # ── Step 0: Advanced Market Structure (rules.md §8) ────────────────────
    ams_blocked, pullback, combined_bias = check_ams_gates(
        ema_trend, signal_type, prev_day_bias, df_1h,
    )
    blocked.extend(ams_blocked)
    h1_status = pullback.get("status", "")

    # ── Rule §2: 30% Body Rule (open AND close in zone) ───────────────────
    from data_fetcher import check_body_rule
    body_valid = False
    if signal_type == SignalType.LONG:
        body_valid = check_body_rule(row, "bullish")
    elif signal_type == SignalType.SHORT:
        body_valid = check_body_rule(row, "bearish")

    if not body_valid and signal_type != SignalType.NONE:
        blocked.append(BlockReason.BODY_RULE_FAILED.value)

    # ── Rule §3: Price at 8 EMA (pullback check) ───────────────────────────
    # Allow 0.5% tolerance around 8 EMA
    ema8_proximity = abs(row["close"] - row["ema_8"]) / row["ema_8"] * 100
    at_8ema        = ema8_proximity <= 0.5

    if not at_8ema and signal_type != SignalType.NONE:
        blocked.append(BlockReason.PRICE_NOT_AT_EMA.value)

    # ── Rule §4: ATR(7) Stop Loss ──────────────────────────────────────────
    atr = row.get("atr_7", 0.0)

    if atr == 0:
        blocked.append(BlockReason.NO_STOP_LOSS.value)

    # ── Capital safeguard (90-90-90) — FLAG only below 80%, do not hard block ─
    flags: list[str] = []
    if capital_pct < 80:
        flags.append(BlockReason.CAPITAL_THRESHOLD.value)

    # ── Build result ───────────────────────────────────────────────────────
    passed = len(blocked) == 0 and signal_type != SignalType.NONE

    entry       = row["close"] if passed else 0.0
    stop_loss   = 0.0
    target_1r   = 0.0

    # Prefer 1H entry close when AMS pullback triggered
    if passed and df_1h is not None and len(df_1h) and pullback.get("entry_ready"):
        entry = float(df_1h.iloc[-1]["close"])

    if passed and atr > 0:
        if signal_type == SignalType.LONG:
            stop_loss = entry - atr         # ATR(7) below entry
            target_1r = entry + (entry - stop_loss)   # 1:1 minimum
        elif signal_type == SignalType.SHORT:
            stop_loss = entry + atr
            target_1r = entry - (stop_loss - entry)

    # ── ruflo-neural-trader: build advisory context ────────────────────────
    regime, regime_note     = assess_regime(df, row)
    anomaly_score, atype    = calc_anomaly_score(df, row)
    circuit_breaker_hits    = check_circuit_breakers(capital_pct, daily_loss_pct, weekly_loss_pct)

    # Collect any detected candlestick patterns from norm_ columns if present
    from data_fetcher import detect_candlestick_patterns
    try:
        detected_patterns = [
            name for name, p in detect_candlestick_patterns(df).items()
            if p["detected"]
        ]
    except Exception:
        detected_patterns = []

    neural_ctx = NeuralContext(
        regime           = regime,
        anomaly_score    = anomaly_score,
        anomaly_type     = atype,
        circuit_breakers = circuit_breaker_hits,
        patterns         = detected_patterns,
        regime_note      = regime_note,
    )

    return SignalResult(
        ticker         = ticker,
        timeframe      = timeframe,
        signal_type    = signal_type,
        passed         = passed,
        entry_price    = entry,
        stop_loss      = stop_loss,
        target_1r      = target_1r,
        ema_trend      = ema_trend,
        body_rule      = body_valid,
        atr_value      = atr,
        blocked_by     = [b for b in blocked],
        flags          = flags,
        neural_context = neural_ctx,
        prev_day_bias  = prev_day_bias,
        prev_day_color = prev_day_color,
        daily_open     = daily_open,
        h1_status      = h1_status,
        combined_bias  = combined_bias,
    )


def run_full_checklist(
    all_data: dict,
    timeframe: str = "1w",
    capital_pct: float = 100.0,
    daily_loss_pct: float = 0.0,
    weekly_loss_pct: float = 0.0,
) -> list:
    """
    Run checklist on all watch list assets and return results.
    Prints a full console report including ruflo-neural-trader context.

    all_data values may be DataFrames (legacy) or market-structure dicts
    with keys: df, df_1h, prev_day_bias, prev_day_color, daily_open.
    """
    results   = []
    confirmed = []
    blocked   = []

    print(f"\n{'='*55}")
    print(f"  COCKPIT CHECKLIST — {timeframe.upper()} Timeframe")
    print(f"  Advanced Market Structure §8 active")
    print(f"  Capital: {capital_pct:.1f}%  |  "
          f"{'⚠ ORANGE — reduce sizing' if capital_pct < 80 else 'OK'}")
    print(f"{'='*55}")

    for ticker, item in all_data.items():
        if isinstance(item, dict):
            df            = item["df"]
            df_1h         = item.get("df_1h")
            prev_day_bias = item.get("prev_day_bias", "")
            prev_day_color = item.get("prev_day_color", "")
            daily_open    = item.get("daily_open", 0.0)
        else:
            df = item
            df_1h = prev_day_bias = prev_day_color = None
            daily_open = 0.0
            prev_day_bias = prev_day_color = ""

        result = check_signal(
            df, ticker, timeframe, capital_pct, daily_loss_pct, weekly_loss_pct,
            df_1h=df_1h,
            prev_day_bias=prev_day_bias or "",
            prev_day_color=prev_day_color or "",
            daily_open=float(daily_open or 0.0),
        )
        if isinstance(item, dict):
            item["h1_status"]     = result.h1_status
            item["combined_bias"] = result.combined_bias

        results.append(result)
        print(result.to_console())

        if result.passed:
            confirmed.append(ticker)
        else:
            blocked.append(ticker)

    # Summary
    print(f"\n{'─'*55}")
    print(f"  SUMMARY")
    print(f"{'─'*55}")
    if confirmed:
        print(f"  ✓ VALID setups:   {', '.join(confirmed)}")
    else:
        print(f"  ✓ VALID setups:   None — wait for clean setup")
    print(f"  ✗ BLOCKED:        {', '.join(blocked) if blocked else 'None'}")
    print(f"{'─'*55}")
    print(f"  Rule: No signal without a confirmed stop-loss (rules.md §4)")
    print(f"  Rule: Weekly bias must be assessed before 4H (rules.md init §5)")
    print(f"  Rule: AMS daily bias + 1H pullback required (rules.md §8)")

    return results


def append_to_decisions_log(
    results: list[SignalResult],
    vault_root: Path = None,
) -> None:
    """Append valid signal rows to logs/decisions-log.md."""
    if vault_root is None:
        vault_root = Path(__file__).parent.parent

    log_path = vault_root / "logs" / "decisions-log.md"
    if not log_path.exists():
        print(f"  ⚠ decisions-log.md not found at {log_path}")
        return

    valid = [r for r in results if r.passed]
    if not valid:
        print("  No valid signals to log.")
        return

    new_rows = "\n".join(r.to_log_row() for r in valid)

    # Append after the table header in the log
    content = log_path.read_text()
    # Find the end of the table header and insert rows
    if "| YYYY-MM-DD |" in content:
        content = content.replace(
            "| YYYY-MM-DD | e.g., 3-Bar Rev",
            new_rows + "\n| YYYY-MM-DD | e.g., 3-Bar Rev",
        )
        log_path.write_text(content)
        print(f"  ✓ Logged {len(valid)} signal(s) to decisions-log.md")
    else:
        # Append to end of file
        with log_path.open("a") as f:
            f.write("\n" + new_rows)
        print(f"  ✓ Appended {len(valid)} signal(s) to decisions-log.md")


if __name__ == "__main__":
    from data_fetcher import fetch_market_structure

    print("Fetching market structure (1W + 1D + 1H)...")
    market_data = fetch_market_structure()

    results = run_full_checklist(
        market_data,
        timeframe="1w",
        capital_pct=100.0,
    )

    # Log any valid signals
    append_to_decisions_log(results)
