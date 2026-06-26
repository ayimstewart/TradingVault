"""
pattern_db.py — Harmonic pattern vector database via turbovec.

Replaces Ruflo AgentDB for pattern matching. Stores historical Gartley,
Butterfly, and Bat completions as 32-dim float32 feature vectors in a
turbovec IdMapIndex (TurboQuant quantized, SIMD-accelerated search).

Use case: after harmonic_detector.py flags a pending D-point, query
find_similar() to see how historically similar setups resolved.

Usage:
    python3 pattern_db.py --status           # show index stats
    python3 pattern_db.py --demo             # add demo patterns + search
    python3 pattern_db.py --query-link       # query LINK Gartley D at 8.4746

Index file: ~/.tradingvault/pattern_db.tvim (auto-created on first add)

References: references/turbovec/README.md
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

VAULT_ROOT = Path(__file__).parent.parent
DB_PATH    = Path.home() / ".tradingvault" / "pattern_db.tvim"
META_PATH  = Path.home() / ".tradingvault" / "pattern_db_meta.json"

DIM       = 32     # vector dimension (16 features + 16 reserved)
BIT_WIDTH = 4      # 4-bit quantization — balanced compression/recall


# ── Feature encoding ──────────────────────────────────────────────────────────
#
# Dimension map (0-indexed):
#   0   XA_range_atr    XA leg size in ATR units
#   1   AB_XA_ratio     AB retracement of XA (Gartley ≈ 0.618, Butterfly ≈ 0.786)
#   2   BC_AB_ratio     BC retracement of AB
#   3   CD_BC_ratio     CD extension of BC
#   4   B_fib           B-point Fibonacci level vs XA
#   5   C_fib           C-point Fibonacci level vs AB
#   6   D_fib           D-point Fibonacci extension level
#   7   ema8_ema20      EMA(8) / EMA(20) at X-point
#   8   ema20_ema50     EMA(20) / EMA(50) at X-point
#   9   price_ema8      Price / EMA(8) at X-point (trend distance)
#   10  atr_price       ATR(7) / price (normalized volatility)
#   11  pattern_type    0=Gartley, 1=Butterfly, 2=Bat, 3=Crab
#   12  direction       +1=bullish (long), -1=bearish (short)
#   13  weekly_bias     +1=FANNING-BULL, -1=FANNING-BEAR, 0=FLAT
#   14  hit_target      +1=yes, -1=no, 0=open (outcome)
#   15  r_achieved      R-multiple achieved (0.0 if still open)
#   16-31               reserved (zeroed)

PATTERN_TYPES = {"gartley": 0, "butterfly": 1, "bat": 2, "crab": 3}


@dataclass
class PatternRecord:
    """One historical or pending pattern entry."""
    pattern_id:   int
    ticker:       str
    pattern_type: str
    direction:    str          # "LONG" | "SHORT"
    weekly_bias:  str          # "FANNING-BULL" | "FANNING-BEAR" | "FLAT"
    detected_at:  str          # ISO datetime
    x_date:       str          # X-point date
    d_price:      float        # D-point price level
    ab_xa_ratio:  float
    bc_ab_ratio:  float
    cd_bc_ratio:  float
    b_fib:        float
    c_fib:        float
    d_fib:        float
    xa_atr_units: float
    ema8_ema20:   float
    ema20_ema50:  float
    price_ema8:   float
    atr_price:    float
    hit_target:   float = 0.0   # +1 / -1 / 0
    r_achieved:   float = 0.0
    notes:        str = ""


def encode_pattern(rec: PatternRecord) -> np.ndarray:
    """Encode a PatternRecord into a 32-dim float32 feature vector."""
    direction = 1.0 if rec.direction == "LONG" else -1.0
    bias_map  = {"FANNING-BULL": 1.0, "FANNING-BEAR": -1.0, "FLAT": 0.0,
                 "CONVERGING": 0.0}
    bias = bias_map.get(rec.weekly_bias, 0.0)
    ptype = float(PATTERN_TYPES.get(rec.pattern_type.lower(), 0))

    features = [
        rec.xa_atr_units,    # 0
        rec.ab_xa_ratio,     # 1
        rec.bc_ab_ratio,     # 2
        rec.cd_bc_ratio,     # 3
        rec.b_fib,           # 4
        rec.c_fib,           # 5
        rec.d_fib,           # 6
        rec.ema8_ema20,      # 7
        rec.ema20_ema50,     # 8
        rec.price_ema8,      # 9
        rec.atr_price,       # 10
        ptype,               # 11
        direction,           # 12
        bias,                # 13
        rec.hit_target,      # 14
        rec.r_achieved,      # 15
    ]
    # Pad to DIM=32
    features += [0.0] * (DIM - len(features))
    return np.array(features, dtype=np.float32)


# ── Index I/O ─────────────────────────────────────────────────────────────────

def _load_meta() -> dict:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text())
    return {"records": {}, "next_id": 1}


def _save_meta(meta: dict) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, indent=2))


def _load_index():
    """Load or create a turbovec IdMapIndex."""
    from turbovec import IdMapIndex
    if DB_PATH.exists():
        try:
            return IdMapIndex.load(str(DB_PATH))
        except Exception:
            pass
    return IdMapIndex(dim=DIM, bit_width=BIT_WIDTH)


# ── Public API ────────────────────────────────────────────────────────────────

def add_pattern(rec: PatternRecord) -> int:
    """
    Add a pattern to the vector index and metadata store.
    Returns the assigned pattern_id.
    """
    from turbovec import IdMapIndex

    meta = _load_meta()
    pid  = meta["next_id"]
    rec.pattern_id = pid

    # Load existing index or create new
    idx = _load_index()
    vec = encode_pattern(rec).reshape(1, DIM)
    ids = np.array([pid], dtype=np.uint64)
    idx.add_with_ids(vec, ids)

    # Persist
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    idx.write(str(DB_PATH))

    meta["records"][str(pid)] = asdict(rec)
    meta["next_id"] = pid + 1
    _save_meta(meta)

    print(f"[pattern_db] Added pattern #{pid}: {rec.pattern_type.upper()} "
          f"{rec.ticker} {rec.direction} @ D={rec.d_price:.4f}")
    return pid


@dataclass
class SimilarPattern:
    pattern_id:   int
    score:        float
    ticker:       str
    pattern_type: str
    direction:    str
    d_price:      float
    detected_at:  str
    hit_target:   float
    r_achieved:   float
    ab_xa_ratio:  float
    b_fib:        float


def find_similar(
    query_rec: PatternRecord,
    k: int = 5,
) -> list[SimilarPattern]:
    """
    Find the k most geometrically similar historical patterns.
    Returns sorted by similarity (highest score first).
    """
    meta = _load_meta()
    if not meta["records"]:
        return []

    idx = _load_index()
    query_vec = encode_pattern(query_rec).reshape(1, DIM)

    actual_k = min(k, len(meta["records"]))
    scores, ids = idx.search(query_vec, k=actual_k)
    scores = scores[0].tolist()
    ids    = ids[0].tolist()

    results: list[SimilarPattern] = []
    for score, pid in zip(scores, ids):
        r = meta["records"].get(str(int(pid)))
        if r is None:
            continue
        results.append(SimilarPattern(
            pattern_id=int(pid),
            score=float(score),
            ticker=r["ticker"],
            pattern_type=r["pattern_type"],
            direction=r["direction"],
            d_price=r["d_price"],
            detected_at=r["detected_at"],
            hit_target=r["hit_target"],
            r_achieved=r["r_achieved"],
            ab_xa_ratio=r["ab_xa_ratio"],
            b_fib=r["b_fib"],
        ))

    return results


def print_similar_report(results: list[SimilarPattern], query_ticker: str) -> None:
    """Print a formatted similarity report for the session notes."""
    if not results:
        print("\n  [pattern_db] No historical patterns in DB yet.")
        print("  Patterns accumulate over sessions — report grows over time.")
        return

    hits = sum(1 for r in results if r.hit_target > 0)
    misses = sum(1 for r in results if r.hit_target < 0)
    open_count = sum(1 for r in results if r.hit_target == 0)

    print(f"\n{'═'*55}")
    print(f"  PATTERN DB — Similar Historical Setups to {query_ticker}")
    print(f"{'═'*55}")
    print(f"  Found {len(results)} similar patterns | "
          f"Hits: {hits} | Misses: {misses} | Open: {open_count}")
    if hits + misses > 0:
        win_rate = hits / (hits + misses) * 100
        avg_r    = sum(r.r_achieved for r in results if r.hit_target != 0) / (hits + misses)
        print(f"  Historical win rate: {win_rate:.0f}% | Avg R: {avg_r:+.2f}")
    print(f"{'─'*55}")

    for r in results:
        outcome = "HIT" if r.hit_target > 0 else ("MISS" if r.hit_target < 0 else "OPEN")
        print(f"  #{r.pattern_id:<4} {r.ticker:<6} {r.pattern_type.upper():<12} "
              f"{r.direction:<5} D={r.d_price:.4f} | {outcome} R={r.r_achieved:+.2f} "
              f"| B={r.ab_xa_ratio:.3f} fib={r.b_fib:.3f} | score={r.score:.2f}")
    print(f"{'═'*55}\n")


def update_outcome(pattern_id: int, hit_target: bool, r_achieved: float) -> None:
    """Update the outcome of a previously pending pattern."""
    from turbovec import IdMapIndex

    meta = _load_meta()
    key  = str(pattern_id)
    if key not in meta["records"]:
        print(f"[pattern_db] Pattern #{pattern_id} not found.")
        return

    rec = meta["records"][key]
    rec["hit_target"]  = 1.0 if hit_target else -1.0
    rec["r_achieved"]  = r_achieved
    meta["records"][key] = rec
    _save_meta(meta)

    # Rebuild index with updated vector
    _rebuild_index(meta)
    outcome = "HIT" if hit_target else "MISS"
    print(f"[pattern_db] #{pattern_id} updated → {outcome} R={r_achieved:+.2f}")


def _rebuild_index(meta: dict) -> None:
    """Rebuild the turbovec index from metadata (needed after outcome updates)."""
    from turbovec import IdMapIndex

    records = meta["records"]
    if not records:
        return

    idx = IdMapIndex(dim=DIM, bit_width=BIT_WIDTH)
    vecs = []
    ids  = []

    for pid_str, r in records.items():
        rec = PatternRecord(**r)
        vecs.append(encode_pattern(rec))
        ids.append(int(pid_str))

    vecs_arr = np.array(vecs, dtype=np.float32)
    ids_arr  = np.array(ids,  dtype=np.uint64)
    idx.add_with_ids(vecs_arr, ids_arr)
    idx.write(str(DB_PATH))


# ── CLI ───────────────────────────────────────────────────────────────────────

def _make_link_gartley() -> PatternRecord:
    """LINK Gartley D-point pending at 8.4746 (from today's alert)."""
    return PatternRecord(
        pattern_id=0,
        ticker="LINK",
        pattern_type="gartley",
        direction="LONG",
        weekly_bias="FANNING-BEAR",
        detected_at=datetime.now(timezone.utc).isoformat(),
        x_date="2026-06-01",
        d_price=8.4746,
        ab_xa_ratio=0.618,
        bc_ab_ratio=0.618,
        cd_bc_ratio=1.27,
        b_fib=0.618,
        c_fib=0.618,
        d_fib=0.786,
        xa_atr_units=2.3,
        ema8_ema20=8.1618 / 9.3065,
        ema20_ema50=9.3065 / 11.7299,
        price_ema8=7.2938 / 8.1618,
        atr_price=0.9743 / 7.2938,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Pattern vector DB (turbovec)")
    parser.add_argument("--status",      action="store_true", help="Show index stats")
    parser.add_argument("--demo",        action="store_true", help="Add demo patterns and run a query")
    parser.add_argument("--query-link",  action="store_true", help="Query DB for LINK Gartley D-point")
    parser.add_argument("--update",      type=int, metavar="ID", help="Pattern ID to update outcome")
    parser.add_argument("--hit",         action="store_true", help="Use with --update: mark as hit")
    parser.add_argument("--r",           type=float, default=0.0, help="R-multiple achieved")
    args = parser.parse_args()

    if args.update:
        update_outcome(args.update, hit_target=args.hit, r_achieved=args.r)
        return

    meta = _load_meta()
    n    = len(meta["records"])

    if args.status:
        print(f"\n[pattern_db] Index: {DB_PATH}")
        print(f"  Patterns stored: {n}")
        print(f"  Next ID:         {meta['next_id']}")
        print(f"  dim={DIM} bit_width={BIT_WIDTH} (TurboQuant 4-bit)")
        return

    if args.demo:
        # Add a few synthetic completed patterns to demonstrate search
        demo_patterns = [
            PatternRecord(0, "BTC",  "gartley",   "LONG",  "FANNING-BULL", "2026-05-01T10:00Z", "2026-04-01", 62000.0, 0.618, 0.618, 1.27, 0.618, 0.618, 0.786, 2.1, 1.05, 1.03, 0.98, 0.009, 1.0, 1.0),
            PatternRecord(0, "ETH",  "butterfly",  "SHORT", "FANNING-BEAR", "2026-04-15T08:00Z", "2026-03-15", 1650.0,  0.786, 0.50,  1.618, 0.786, 0.50, 1.27,  1.8, 0.94, 0.92, 1.02, 0.013, -1.0, -1.0),
            PatternRecord(0, "LINK", "gartley",   "LONG",  "FANNING-BEAR", "2026-03-20T12:00Z", "2026-02-20", 9.2000,  0.618, 0.650, 1.27, 0.618, 0.640, 0.786, 2.4, 0.88, 0.80, 0.95, 0.105, 1.0, 1.0),
            PatternRecord(0, "SOL",  "bat",       "LONG",  "CONVERGING",   "2026-02-10T09:00Z", "2026-01-10", 80.00,   0.50,  0.618, 1.618, 0.50, 0.618, 0.886, 1.5, 1.01, 0.98, 1.00, 0.013, -1.0, -1.0),
            PatternRecord(0, "LINK", "gartley",   "LONG",  "FANNING-BEAR", "2026-01-05T14:00Z", "2025-12-01", 10.5000, 0.620, 0.630, 1.28, 0.620, 0.640, 0.790, 2.2, 0.87, 0.81, 0.96, 0.093, 1.0, 1.0),
        ]
        print("\n[pattern_db] Adding 5 demo patterns...")
        for p in demo_patterns:
            add_pattern(p)
        print("\n  Demo patterns added. Now querying for LINK Gartley similarity...\n")

    if args.demo or args.query_link:
        query = _make_link_gartley()
        results = find_similar(query, k=5)
        print_similar_report(results, "LINK Gartley D@8.4746")


if __name__ == "__main__":
    main()
