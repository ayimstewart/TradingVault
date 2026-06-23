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


class SignalType(Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    NONE  = "NONE"


class BlockReason(Enum):
    EMA_NOT_FANNING      = "EMA not fanning — trend invalid (rules.md §1)"
    BODY_RULE_FAILED     = "Candle body not in valid zone (rules.md §2)"
    NO_STOP_LOSS         = "No ATR(7) stop calculated (rules.md §4)"
    PRICE_NOT_AT_EMA     = "Price not at 8 EMA — wait for pullback"
    SILLY_DONATION_FOMO  = "FOMO detected — move already in progress (BLOCKED)"
    SILLY_DONATION_FORCE = "Forced setup — no valid confluence (BLOCKED)"
    CAPITAL_THRESHOLD    = "Capital below safe threshold — sizing reduced"


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
        lines.append(f"{'═'*55}")
        return "\n".join(lines)


def check_signal(
    df: pd.DataFrame,
    ticker: str,
    timeframe: str = "1w",
    capital_pct: float = 100.0,
) -> SignalResult:
    """
    Run the full Cockpit Checklist against the latest candle.

    Args:
        df:           DataFrame with columns: open, high, low, close,
                      ema_8, ema_20, ema_50, atr_7
                      (output of data_fetcher.add_ema + add_atr)
        ticker:       Asset name e.g. "BTC"
        timeframe:    Timeframe string e.g. "1w", "4h"
        capital_pct:  Current capital as % of starting capital (90-90-90 check)

    Returns:
        SignalResult — fully populated, blocked or confirmed.
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

    # ── Rule §2: 30% Body Rule ─────────────────────────────────────────────
    candle_range = row["high"] - row["low"]
    body_valid   = False

    if candle_range > 0:
        if signal_type == SignalType.LONG:
            threshold  = row["high"] - (candle_range * 0.30)
            body_valid = row["close"] >= threshold
        elif signal_type == SignalType.SHORT:
            threshold  = row["low"] + (candle_range * 0.30)
            body_valid = row["close"] <= threshold

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

    # ── Capital safeguard (90-90-90) ───────────────────────────────────────
    if capital_pct < 80:
        blocked.append(BlockReason.CAPITAL_THRESHOLD.value)
        # Don't hard block — just flag. Human decides whether to size down.

    # ── Build result ───────────────────────────────────────────────────────
    passed = len(blocked) == 0 and signal_type != SignalType.NONE

    entry       = row["close"] if passed else 0.0
    stop_loss   = 0.0
    target_1r   = 0.0

    if passed and atr > 0:
        if signal_type == SignalType.LONG:
            stop_loss = entry - atr         # ATR(7) below entry
            target_1r = entry + (entry - stop_loss)   # 1:1 minimum
        elif signal_type == SignalType.SHORT:
            stop_loss = entry + atr
            target_1r = entry - (stop_loss - entry)

    return SignalResult(
        ticker      = ticker,
        timeframe   = timeframe,
        signal_type = signal_type,
        passed      = passed,
        entry_price = entry,
        stop_loss   = stop_loss,
        target_1r   = target_1r,
        ema_trend   = ema_trend,
        body_rule   = body_valid,
        atr_value   = atr,
        blocked_by  = [b for b in blocked],
    )


def run_full_checklist(
    all_data: dict[str, pd.DataFrame],
    timeframe: str = "1w",
    capital_pct: float = 100.0,
) -> list[SignalResult]:
    """
    Run checklist on all watch list assets and return results.
    Prints a full console report.
    """
    results   = []
    confirmed = []
    blocked   = []

    print(f"\n{'='*55}")
    print(f"  COCKPIT CHECKLIST — {timeframe.upper()} Timeframe")
    print(f"  Capital: {capital_pct:.1f}%  |  "
          f"{'⚠ ORANGE — reduce sizing' if capital_pct < 80 else 'OK'}")
    print(f"{'='*55}")

    for ticker, df in all_data.items():
        result = check_signal(df, ticker, timeframe, capital_pct)
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
    # Demo: pull data and run checklist
    from data_fetcher import fetch_all_assets

    print("Fetching weekly data...")
    weekly_data = fetch_all_assets(timeframe="1w")

    results = run_full_checklist(
        weekly_data,
        timeframe="1w",
        capital_pct=100.0,
    )

    # Log any valid signals
    append_to_decisions_log(results)
