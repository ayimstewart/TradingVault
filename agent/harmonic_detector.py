"""
harmonic_detector.py — Gartley / Butterfly pattern detection per rules.md §3.

Enforces:
  - B at 0.618 retracement of X→A (Gartley)
  - B touching 0.786 → reclassify as Butterfly or INVALID GARTLEY
  - C >= 0.618 retracement of A→B, must NOT penetrate A
  - D completion at 1.27 extension of A→B (entry zone)

Run:  python3 harmonic_detector.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

import pandas as pd

# Fibonacci ratios used by Cockpit Checklist
FIB_B_GARTLEY = 0.618
FIB_B_BUTTERFLY = 0.786
FIB_C_MIN = 0.618
FIB_D_EXT = 1.27

# Tolerance for ratio matching (crypto volatility)
RATIO_TOLERANCE = 0.05


class PatternType(Enum):
    GARTLEY = "GARTLEY"
    BUTTERFLY = "BUTTERFLY"
    INVALID = "INVALID"
    PENDING = "PENDING"


class PatternStatus(Enum):
    COMPLETE = "COMPLETE"       # D-point reached — entry zone
    PENDING_D = "PENDING — Await D-point completion"
    INVALID = "INVALID"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: Literal["high", "low"]


@dataclass
class HarmonicResult:
    ticker: str
    timeframe: str
    pattern: PatternType
    status: PatternStatus
    x: float = 0.0
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    d_target: float = 0.0
    b_ratio: float = 0.0
    c_ratio: float = 0.0
    direction: str = ""          # "bullish" or "bearish"
    notes: list[str] = field(default_factory=list)

    def to_console(self) -> str:
        lines = [
            f"  Pattern:   {self.pattern.value}",
            f"  Status:    {self.status.value}",
            f"  Direction: {self.direction or '—'}",
            f"  X/A/B/C:   {self.x:.4f} / {self.a:.4f} / {self.b:.4f} / {self.c:.4f}",
            f"  B ratio:   {self.b_ratio:.3f} (target 0.618 Gartley)",
            f"  C ratio:   {self.c_ratio:.3f} (min 0.618 AB)",
            f"  D target:  {self.d_target:.4f} (1.27 ext AB)",
        ]
        for note in self.notes:
            lines.append(f"  → {note}")
        return "\n".join(lines)


def find_swing_points(
    df: pd.DataFrame,
    lookback: int = 3,
) -> list[SwingPoint]:
    """Identify local highs/lows for harmonic leg construction."""
    swings: list[SwingPoint] = []

    for i in range(lookback, len(df) - lookback):
        window_high = df["high"].iloc[i - lookback : i + lookback + 1]
        window_low = df["low"].iloc[i - lookback : i + lookback + 1]
        price_high = df["high"].iloc[i]
        price_low = df["low"].iloc[i]

        if price_high >= window_high.max():
            swings.append(SwingPoint(index=i, price=price_high, kind="high"))
        elif price_low <= window_low.min():
            swings.append(SwingPoint(index=i, price=price_low, kind="low"))

    # Remove consecutive same-kind swings — keep the more extreme
    cleaned: list[SwingPoint] = []
    for swing in swings:
        if cleaned and cleaned[-1].kind == swing.kind:
            prev = cleaned[-1]
            if swing.kind == "high" and swing.price >= prev.price:
                cleaned[-1] = swing
            elif swing.kind == "low" and swing.price <= prev.price:
                cleaned[-1] = swing
        else:
            cleaned.append(swing)

    return cleaned


def _within_tolerance(actual: float, target: float, tol: float = RATIO_TOLERANCE) -> bool:
    return abs(actual - target) <= tol


def validate_gartley_legs(
    x: float,
    a: float,
    b: float,
    c: float,
    direction: str,
) -> HarmonicResult:
    """
    Validate X-A-B-C legs against rules.md §3 harmonic rules.
    Returns classification and D-point target if pattern is valid/pending.
    """
    xa = abs(a - x)
    ab = abs(b - a)
    notes: list[str] = []

    if xa == 0 or ab == 0:
        return HarmonicResult(
            ticker="", timeframe="", pattern=PatternType.INVALID,
            status=PatternStatus.INVALID, notes=["Zero-length leg — discard"],
        )

    # B-point ratio of X→A leg
    b_ratio = abs(b - a) / xa

    # C must retrace >= 0.618 of A→B
    c_ratio = abs(c - b) / ab

    # D target: 1.27 extension of A→B from C
    if direction == "bullish":
        d_target = c - (ab * FIB_D_EXT) if a > x else c + (ab * FIB_D_EXT)
        c_violates_a = c < a if a > x else c > a
        b_touches_786 = _within_tolerance(b_ratio, FIB_B_BUTTERFLY) or b_ratio >= FIB_B_BUTTERFLY - RATIO_TOLERANCE
    else:
        d_target = c + (ab * FIB_D_EXT) if a < x else c - (ab * FIB_D_EXT)
        c_violates_a = c > a if a < x else c < a
        b_touches_786 = _within_tolerance(b_ratio, FIB_B_BUTTERFLY) or b_ratio >= FIB_B_BUTTERFLY - RATIO_TOLERANCE

    result = HarmonicResult(
        ticker="", timeframe="",
        pattern=PatternType.PENDING,
        status=PatternStatus.PENDING_D,
        x=x, a=a, b=b, c=c,
        d_target=d_target,
        b_ratio=b_ratio,
        c_ratio=c_ratio,
        direction=direction,
    )

    # Hard rule: C must not penetrate A
    if c_violates_a:
        result.pattern = PatternType.INVALID
        result.status = PatternStatus.INVALID
        result.notes.append("C penetrated A-point — pattern INVALID, discard entirely")
        return result

    # C must hit >= 0.618 of AB
    if c_ratio < FIB_C_MIN - RATIO_TOLERANCE:
        result.pattern = PatternType.INVALID
        result.status = PatternStatus.INVALID
        result.notes.append(f"C ratio {c_ratio:.3f} below 0.618 minimum")
        return result

    # B at 0.786 → Butterfly reclassification
    if b_touches_786:
        result.pattern = PatternType.BUTTERFLY
        result.notes.append("B touched 0.786 — reclassified from Gartley to Butterfly")
        if not _within_tolerance(b_ratio, FIB_B_BUTTERFLY):
            result.status = PatternStatus.INVALID
            result.notes.append("B ratio outside Butterfly tolerance — mark INVALID GARTLEY")
            return result
        result.notes.append(f"Watch D at 1.27 ext of AB: {d_target:.4f}")
        return result

    # Gartley: B must be at 0.618
    if not _within_tolerance(b_ratio, FIB_B_GARTLEY):
        result.pattern = PatternType.INVALID
        result.status = PatternStatus.INVALID
        result.notes.append(f"NOT a Gartley — B ratio {b_ratio:.3f} ≠ 0.618")
        return result

    result.pattern = PatternType.GARTLEY
    result.notes.append(f"GARTLEY — Watch D at 1.27 ext of AB: {d_target:.4f}")
    result.notes.append("PENDING — Await D-point completion")
    return result


def detect_harmonic(
    df: pd.DataFrame,
    ticker: str = "",
    timeframe: str = "1w",
    lookback: int = 3,
) -> HarmonicResult:
    """
    Scan recent swing structure for the most recent valid Gartley/Butterfly setup.
    Uses the last 5 swing points to form X-A-B-C legs.
    """
    swings = find_swing_points(df, lookback=lookback)

    if len(swings) < 5:
        return HarmonicResult(
            ticker=ticker,
            timeframe=timeframe,
            pattern=PatternType.INVALID,
            status=PatternStatus.NOT_FOUND,
            notes=[f"Insufficient swing points ({len(swings)}/5 required)"],
        )

    # Use the 5 most recent alternating swings as X-A-B-C (+ prior for X)
    recent = swings[-5:]
    x_pt, a_pt, b_pt, c_pt = recent[0], recent[1], recent[2], recent[3]

    # Bullish Gartley: X low → A high → B low → C high (or mirrored)
    if x_pt.kind == "low" and a_pt.kind == "high":
        direction = "bullish"
    elif x_pt.kind == "high" and a_pt.kind == "low":
        direction = "bearish"
    else:
        return HarmonicResult(
            ticker=ticker,
            timeframe=timeframe,
            pattern=PatternType.INVALID,
            status=PatternStatus.NOT_FOUND,
            notes=["Swing sequence does not form X-A alternation"],
        )

    result = validate_gartley_legs(
        x=x_pt.price,
        a=a_pt.price,
        b=b_pt.price,
        c=c_pt.price,
        direction=direction,
    )
    result.ticker = ticker
    result.timeframe = timeframe

    # Check if current price has reached D zone (within 1% tolerance)
    if result.status == PatternStatus.PENDING_D and result.d_target > 0:
        current = df["close"].iloc[-1]
        proximity = abs(current - result.d_target) / result.d_target * 100
        if proximity <= 1.0:
            result.status = PatternStatus.COMPLETE
            result.notes.append(f"D-point zone reached — current {current:.4f}")

    return result


def scan_watch_list(
    all_data: dict[str, pd.DataFrame],
    timeframe: str = "1w",
) -> list[HarmonicResult]:
    """Run harmonic scan on all assets. Prints console report."""
    results: list[HarmonicResult] = []

    print(f"\n{'='*55}")
    print(f"  HARMONIC SCAN — {timeframe.upper()} Timeframe")
    print(f"  Gartley / Butterfly per rules.md §3")
    print(f"{'='*55}")

    for ticker, df in all_data.items():
        result = detect_harmonic(df, ticker=ticker, timeframe=timeframe)
        results.append(result)

        print(f"\n{'─'*55}")
        print(f"  {ticker}")
        print(f"{'─'*55}")
        print(result.to_console())

    pending = [r for r in results if r.status == PatternStatus.PENDING_D]
    complete = [r for r in results if r.status == PatternStatus.COMPLETE]

    print(f"\n{'─'*55}")
    print(f"  HARMONIC SUMMARY")
    print(f"{'─'*55}")
    print(f"  Pending D:  {', '.join(r.ticker for r in pending) or 'None'}")
    print(f"  Complete:   {', '.join(r.ticker for r in complete) or 'None'}")
    print(f"{'─'*55}")

    return results


if __name__ == "__main__":
    from data_fetcher import fetch_all_assets

    print("Fetching weekly data for harmonic scan...")
    weekly_data = fetch_all_assets(timeframe="1w")
    scan_watch_list(weekly_data, timeframe="1w")
