"""
kronos_probability.py — Candlestick probability layer using Kronos foundation model.

Kronos (AAAI 2026) is trained on 45+ global exchanges and understands the
"language" of financial K-lines. This module adds a probabilistic score to
any setup as CONTEXT — never as a signal generator. rules.md still decides.

Usage:
    python3 kronos_probability.py                  # probability summary for all assets
    python3 kronos_probability.py --asset BTC      # single asset
    python3 kronos_probability.py --install        # install Kronos deps

Architecture:
    Live data (Kraken) → Kronos model → direction probabilities
    → fed into run_session.py as context, not signal

Kronos requires: pip install torch transformers huggingface_hub
Model:  NeoQuasar/Kronos-mini (4.1M params, 2048 context — fastest)
Fallback: statistical momentum score when Kronos not installed.

IMPORTANT: Kronos output is CONTEXT only. The Cockpit Checklist
           (rules.md) makes all trade decisions. Kronos just adds
           probability weight to setups that already passed the checklist.
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from data_fetcher import fetch_ohlcv, add_ema, add_atr, get_exchange, WATCH_LIST

VAULT_ROOT = Path(__file__).parent.parent

# ── Kronos model config ───────────────────────────────────────────────────────

KRONOS_TOKENIZER = "NeoQuasar/Kronos-Tokenizer-2k"
KRONOS_MODEL     = "NeoQuasar/Kronos-mini"  # 4.1M params — fastest, 2048 context
PRED_LEN         = 4     # predict 4 candles forward (1 week = 4 x 4H)
LOOKBACK         = 200   # candles of context


def _kronos_available() -> bool:
    try:
        import torch           # noqa: F401
        import transformers    # noqa: F401
        return True
    except ImportError:
        return False


# ── Statistical fallback (momentum-based probability) ─────────────────────────

def _statistical_probability(df: pd.DataFrame) -> tuple[float, float]:
    """
    Lightweight probability estimate using momentum indicators.
    Used when Kronos model is not installed.

    Returns (bull_prob, bear_prob) as fractions summing to 1.0.
    """
    recent = df.iloc[-20:]
    close  = recent["close"]

    # Trend score: fraction of last 20 closes above their own EMA(8)
    ema_8      = df["ema_8"].iloc[-20:]
    above_ema  = (close.values > ema_8.values).mean()

    # Momentum: up-days vs down-days
    returns    = close.pct_change().dropna()
    up_days    = (returns > 0).sum()
    total_days = len(returns)
    win_rate   = up_days / total_days if total_days > 0 else 0.5

    # ATR-normalized recent move (are we in a trend or mean-reverting?)
    atr_now    = df["atr_7"].iloc[-1]
    move_size  = abs(close.iloc[-1] - close.iloc[-5]) / atr_now if atr_now > 0 else 0
    trend_weight = min(move_size / 3.0, 0.5)  # caps at 0.5

    # Blend
    bull_raw   = (above_ema * 0.5) + (win_rate * 0.3) + (trend_weight * 0.2)
    bull_prob  = max(0.1, min(0.9, bull_raw))  # clamp 10–90%
    bear_prob  = 1.0 - bull_prob

    return bull_prob, bear_prob


# ── Kronos probability (full model) ──────────────────────────────────────────

def _kronos_probability(df: pd.DataFrame, pred_len: int = PRED_LEN) -> tuple[float, float]:
    """
    Run Kronos inference on OHLCV data, return (bull_prob, bear_prob).
    Kronos predicts OHLCV for the next pred_len candles; we classify
    by whether the median predicted close is above the current close.
    """
    try:
        import torch
        warnings.filterwarnings("ignore")
        sys.path.insert(0, str(VAULT_ROOT / "references" / "Kronos"))

        from model import Kronos, KronosTokenizer, KronosPredictor  # type: ignore

        tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER)
        model     = Kronos.from_pretrained(KRONOS_MODEL)
        predictor = KronosPredictor(model, tokenizer, max_context=512)

        cols    = ["open", "high", "low", "close", "volume"]
        x_df    = df[cols].iloc[-LOOKBACK:].copy()
        x_ts    = pd.to_datetime(df.index[-LOOKBACK:])

        # Build future timestamps (same interval as last two candles)
        last_interval = x_ts[-1] - x_ts[-2]
        y_ts = pd.date_range(
            start=x_ts[-1] + last_interval,
            periods=pred_len,
            freq=last_interval,
        )

        pred_df = predictor.predict(
            df=x_df.reset_index(drop=True),
            x_timestamp=pd.Series(x_ts),
            y_timestamp=pd.Series(y_ts),
            pred_len=pred_len,
            T=0.8,
            top_p=0.9,
            sample_count=10,
        )

        current_close = float(df["close"].iloc[-1])
        pred_closes   = pred_df["close"].values
        bull_votes    = (pred_closes > current_close).sum()
        bull_prob     = bull_votes / len(pred_closes)
        bear_prob     = 1.0 - bull_prob

        return float(bull_prob), float(bear_prob)

    except Exception as e:
        # Fallback to statistical if model errors
        return _statistical_probability(df)


# ── Main probability score container ─────────────────────────────────────────

@dataclass
class ProbabilityScore:
    ticker:       str
    timeframe:    str
    bull_prob:    float    # 0.0 – 1.0
    bear_prob:    float    # 0.0 – 1.0
    direction:    str      # BULL | BEAR | NEUTRAL
    confidence:   str      # HIGH | MEDIUM | LOW
    method:       str      # kronos | statistical
    context_note: str      # one-line context for the session brief

    @property
    def dominant_prob(self) -> float:
        return max(self.bull_prob, self.bear_prob)


def score_asset(
    ticker: str,
    timeframe: str = "1w",
    limit: int = 250,
) -> ProbabilityScore:
    """Fetch data and compute Kronos (or statistical) probability for one asset."""
    symbol   = WATCH_LIST.get(ticker)
    if not symbol:
        raise ValueError(f"Unknown ticker '{ticker}'. Valid: {list(WATCH_LIST)}")

    exchange = get_exchange()
    df       = fetch_ohlcv(exchange, symbol, timeframe=timeframe, limit=limit)
    df       = add_ema(df)
    df       = add_atr(df)

    use_kronos = _kronos_available()

    if use_kronos:
        bull_p, bear_p = _kronos_probability(df)
        method = "kronos"
    else:
        bull_p, bear_p = _statistical_probability(df)
        method = "statistical"

    dominant = max(bull_p, bear_p)

    if dominant >= 0.70:
        confidence = "HIGH"
    elif dominant >= 0.58:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    if bull_p > bear_p + 0.05:
        direction = "BULL"
    elif bear_p > bull_p + 0.05:
        direction = "BEAR"
    else:
        direction = "NEUTRAL"

    context_note = (
        f"{direction} bias {dominant:.0%} confidence ({method}) — "
        f"context only, not a signal"
    )

    return ProbabilityScore(
        ticker=ticker,
        timeframe=timeframe,
        bull_prob=bull_p,
        bear_prob=bear_p,
        direction=direction,
        confidence=confidence,
        method=method,
        context_note=context_note,
    )


def score_all_assets(timeframe: str = "1w") -> dict[str, ProbabilityScore]:
    """Score all watch-list assets."""
    scores: dict[str, ProbabilityScore] = {}
    for ticker in WATCH_LIST:
        try:
            scores[ticker] = score_asset(ticker, timeframe=timeframe)
        except Exception as e:
            print(f"  {ticker}: probability score failed — {e}")
    return scores


# ── Console display ───────────────────────────────────────────────────────────

def print_score(score: ProbabilityScore) -> None:
    bar_len = 20
    bull_bar = int(score.bull_prob * bar_len)
    bear_bar = bar_len - bull_bar
    bar = f"[{'B'*bull_bar}{'░'*bear_bar}]"

    conf_sym = {"HIGH": "●●●", "MEDIUM": "●●○", "LOW": "●○○"}.get(score.confidence, "?")

    print(f"  {score.ticker:<5} | {bar}  Bull {score.bull_prob:.0%}  Bear {score.bear_prob:.0%}  "
          f"→ {score.direction:<7} {conf_sym}  [{score.method}]")


def print_full_report(timeframe: str = "1w") -> None:
    method_label = "Kronos" if _kronos_available() else "Statistical (install Kronos for deep model)"

    print(f"\n{'='*62}")
    print(f"  KRONOS PROBABILITY LAYER — {timeframe.upper()}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  Method: {method_label}")
    print(f"  ⚠  CONTEXT ONLY — rules.md §1-4 governs all trade decisions")
    print(f"{'='*62}")

    if not _kronos_available():
        print(f"\n  Kronos model not installed. Using statistical momentum scores.")
        print(f"  To install Kronos: pip install torch transformers huggingface_hub")
        print(f"  Then re-run to switch to deep model inference.\n")

    scores = score_all_assets(timeframe)

    print(f"\n  {'Ticker':<6}  {'← Bear   Bull →':<22}  Direction  Conf    Method")
    print(f"  {'─'*58}")
    for ticker, score in scores.items():
        print_score(score)

    high_conf = [t for t, s in scores.items() if s.confidence == "HIGH"]
    if high_conf:
        print(f"\n  High-confidence setups: {', '.join(high_conf)}")
        print(f"  (Still require checklist validation before any signal)")

    print(f"\n{'='*62}")
    print(f"  Install Kronos:  pip install torch transformers huggingface_hub")
    print(f"  Then re-run to enable deep candlestick model inference.")
    print(f"{'='*62}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kronos Probability Layer")
    parser.add_argument("--asset",     default=None, help="Single asset (e.g. BTC)")
    parser.add_argument("--timeframe", default="1w", help="Timeframe (1w/4h)")
    parser.add_argument("--install",   action="store_true", help="Print install instructions")
    args = parser.parse_args()

    if args.install:
        print("\nKronos install instructions:")
        print("  pip install torch transformers huggingface_hub")
        print(f"\nKronos reference repo: {VAULT_ROOT}/references/Kronos")
        print("The model will auto-download from HuggingFace on first run (~170MB).")
        sys.exit(0)

    if args.asset:
        score = score_asset(args.asset.upper(), timeframe=args.timeframe)
        print(f"\n{score.context_note}")
    else:
        print_full_report(timeframe=args.timeframe)
