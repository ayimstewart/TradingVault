"""
full_pipeline.py — MASTER ORCHESTRATOR.

One command. Everything fires in sequence.

    python3 full_pipeline.py
    python3 full_pipeline.py --account 10000   # enables position sizing

Execution order:
    1. quant_mind_fetcher  — arXiv + web research digest
    2. notebooklm_bridge   — query Green Bread Coach(GBC)
    3. data_fetcher        — live 1W OHLCV from Kraken
    4. signal_checker      — Cockpit Checklist (rules.md §1–4)
    5. pattern_db          — turbovec historical pattern match
    6. apex_guard          — PA-50K trailing drawdown check
    6b. rithmic_executor   — Apex CME micro-futures (dry-run default)
    7. robinhood_executor  — stage orders for apex-cleared signals
    8. ai_trader_publisher — publish apex-cleared signals to ai4trade.ai
    9. Log to logs/decisions-log.md + Morning Brief to sources/
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

VAULT_ROOT  = Path(__file__).parent.parent
RULES_PATH  = VAULT_ROOT / "rules" / "rules.md"
LOG_PATH    = VAULT_ROOT / "logs"  / "decisions-log.md"

sys.path.insert(0, str(Path(__file__).parent))

WATCH_LIST  = ["BTC", "ETH", "SOL", "XRP", "LINK", "PEPE"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _banner(step: int, title: str) -> None:
    print(f"\n{'='*58}")
    print(f"  [STEP {step}] {title}")
    print(f"{'='*58}")


def _warn(label: str, exc: Exception) -> None:
    print(f"  ⚠ {label} failed: {exc}")


# ── Step 1: quant_mind_fetcher ─────────────────────────────────────────────────

def step_1_research_digest() -> Path | None:
    _banner(1, "Research Digest — arXiv + Web")
    try:
        from quant_mind_fetcher import (
            fetch_all_papers, fetch_web_content,
            format_digest, save_digest, import_to_notebooklm,
        )
        papers   = fetch_all_papers(days=1)
        web      = fetch_web_content(skip_web=False)
        content  = format_digest(papers, days=1, web_items=web)
        path     = save_digest(content)
        print(f"  ✓ Digest saved: {path.name}")
        import_to_notebooklm(path)
        return path
    except Exception as e:
        _warn("quant_mind_fetcher", e)
        return None


# ── Step 2: notebooklm_bridge ─────────────────────────────────────────────────

def step_2_notebooklm(digest_path: Path | None) -> dict:
    _banner(2, "NotebookLM — Green Bread Coach(GBC)")
    try:
        from notebooklm_bridge import run_morning_queries
        results = run_morning_queries(brief_path=digest_path, verbose=True)
        print(f"  ✓ NotebookLM queries complete")
        return results
    except Exception as e:
        _warn("notebooklm_bridge", e)
        return {}


# ── Step 3: data_fetcher ───────────────────────────────────────────────────────

def step_3_fetch_data() -> dict:
    _banner(3, "OHLCV — Kraken (1W + 1D + 1H AMS)")
    from data_fetcher import fetch_market_structure
    data = fetch_market_structure()
    print(f"  ✓ Fetched {len(data)} assets: {', '.join(data.keys())}")
    return data


# ── Step 4: signal_checker ────────────────────────────────────────────────────

def step_4_checklist(weekly_data: dict, capital_pct: float) -> list:
    _banner(4, "Cockpit Checklist (rules.md §1–4 + §8 AMS)")
    from signal_checker import run_full_checklist
    from harmonic_detector import scan_watch_list
    results = run_full_checklist(weekly_data, timeframe="1w", capital_pct=capital_pct)
    print("\n  Running harmonic scan...")
    weekly_dfs = {
        t: (v["df"] if isinstance(v, dict) else v)
        for t, v in weekly_data.items()
    }
    scan_watch_list(weekly_dfs, timeframe="1w")
    return results


# ── Step 5: pattern_db ────────────────────────────────────────────────────────

def step_5_pattern_db(signal_results: list) -> None:
    _banner(5, "Pattern DB — turbovec historical match")
    valid = [r for r in signal_results if getattr(r, "passed", False)]
    if not valid:
        print("  No confirmed signals — pattern DB query skipped")
        return
    try:
        from pattern_db import find_similar, PatternRecord, print_similar_report, _load_meta
        meta   = _load_meta()
        stored = len(meta.get("records", {}))
        print(f"  Pattern DB: {stored} historical pattern(s) stored")
        if stored == 0:
            print("  DB empty — run pattern_db.py --demo to seed it")
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for sig in valid:
            rec = PatternRecord(
                pattern_id   = 0,
                ticker       = sig.ticker,
                pattern_type = "TCL",
                direction    = sig.signal_type.value,
                weekly_bias  = sig.ema_trend,
                detected_at  = today,
                x_date       = today,
                d_price      = sig.entry_price,
                ab_xa_ratio  = 0.618,
                bc_ab_ratio  = 0.618,
                cd_bc_ratio  = 1.0,
                b_fib        = 0.618,
                c_fib        = 0.618,
                d_fib        = 1.272,
                xa_atr_units = 1.0,
                ema8_ema20   = sig.entry_price / sig.stop_loss if sig.stop_loss > 0 else 1.0,
                ema20_ema50  = 1.0,
                price_ema8   = 1.0 if sig.body_rule else 0.0,
                atr_price    = sig.atr_value / sig.entry_price if sig.entry_price > 0 else 0.0,
            )
            similar = find_similar(rec, k=3)
            if similar:
                print_similar_report(similar, sig.ticker)
    except ImportError:
        print("  turbovec not installed — pattern DB skipped")
    except Exception as e:
        _warn("pattern_db", e)


# ── Step 6: apex_guard ────────────────────────────────────────────────────────

def step_6_apex_guard(signal_results: list) -> list:
    """
    Run Apex trailing drawdown check for each confirmed signal.
    Returns only the signals that pass apex guard (safe to execute).
    """
    _banner(6, "Apex Guard — PA-50K Drawdown Protection")
    from apex_guard import check_apex_guard

    apex_cleared: list = []
    for sig in signal_results:
        if not getattr(sig, "passed", False):
            continue
        guard = check_apex_guard(atr_7=sig.atr_value)
        print(guard.to_console())
        if guard.passed:
            apex_cleared.append(sig)
        else:
            print(f"  ✗ {sig.ticker} BLOCKED by apex guard — signal dropped")

    print(f"\n  Apex-cleared signals: {len(apex_cleared)}/{len([r for r in signal_results if r.passed])}")
    return apex_cleared


# ── Step 6b: rithmic_executor ─────────────────────────────────────────────────

def step_6b_rithmic(apex_cleared: list, live: bool = False) -> list[dict]:
    """
    Stage (or submit) Apex CME micro-futures bracket orders via Rithmic.
    Runs in dry-run mode by default; pass live=True only when confirmed.
    """
    _banner("6b", "Rithmic Executor — Apex CME Micro-Futures")
    try:
        from rithmic_executor import execute_apex_cleared
        results = execute_apex_cleared(apex_cleared, live=live)
        submitted = sum(1 for r in results if r.get("status") == "submitted")
        staged    = sum(1 for r in results if r.get("status") == "staged")
        blocked   = sum(1 for r in results if "blocked" in r.get("status", ""))
        print(f"\n  Rithmic: {submitted} submitted | {staged} staged | {blocked} blocked")
        return results
    except Exception as e:
        _warn("rithmic_executor", e)
        return []


# ── Step 7: robinhood_executor ────────────────────────────────────────────────

def step_7_robinhood(
    apex_cleared: list,
    account_balance: float | None,
) -> list[dict]:
    """
    Build and stage Robinhood orders for apex-cleared signals.
    Returns list of order dicts (logged to decisions-log.md).
    """
    _banner(7, "Robinhood Executor — Stage Orders")

    if not apex_cleared:
        print("  No apex-cleared signals — Robinhood step skipped")
        return []

    if account_balance is None:
        print("  Account balance not set (--account not provided)")
        print("  MCP call parameters printed for reference only (no sizing)\n")

    from robinhood_executor import build_equity_order, format_mcp_call, log_pending_order
    from position_sizer import size_position

    orders: list[dict] = []
    for sig in apex_cleared:
        if sig.stop_loss <= 0:
            print(f"  ✗ {sig.ticker} skipped — no ATR(7) stop (rules.md §4)")
            continue

        if account_balance is not None:
            card  = size_position(sig, account_balance=account_balance)
            units = card.position_units
            print(card.to_console())
        else:
            units = 1.0

        order = build_equity_order(
            ticker     = sig.ticker,
            direction  = sig.signal_type.value,
            entry_price= sig.entry_price,
            stop_loss  = sig.stop_loss,
            target_1r  = sig.target_1r,
            quantity   = units,
        )
        print(format_mcp_call(order))
        log_pending_order(order, note="Staged by full_pipeline.py")
        orders.append(order)

    return orders


# ── Step 8: ai_trader_publisher ───────────────────────────────────────────────

def step_8_publish(apex_cleared: list, brief_text: str) -> dict:
    from ai_trader_publisher import run_pipeline_step
    return run_pipeline_step(apex_cleared, brief_text, WATCH_LIST)


# ── Step 9: log + morning brief ───────────────────────────────────────────────

def step_9_log_and_brief(
    weekly_data: dict,
    signal_results: list,
    nlm_results: dict,
) -> Path | None:
    _banner(9, "Log to decisions-log.md + Save Morning Brief")
    from signal_checker import append_to_decisions_log
    from data_fetcher   import save_morning_brief
    from notebooklm_bridge import save_session_note

    append_to_decisions_log(signal_results, vault_root=VAULT_ROOT)

    brief_data = {
        ticker: {
            "df":             info["df"] if isinstance(info, dict) else info,
            "prev_day_color": info.get("prev_day_color", "—") if isinstance(info, dict) else "—",
            "daily_open":     info.get("daily_open", 0.0) if isinstance(info, dict) else 0.0,
            "h1_status":      info.get("h1_status", "—") if isinstance(info, dict) else "—",
            "combined_bias":  info.get("combined_bias", "—") if isinstance(info, dict) else "—",
        }
        for ticker, info in weekly_data.items()
    }
    brief_path = save_morning_brief(brief_data)
    print(f"  ✓ Morning Brief: {brief_path.name}")

    valid   = [r for r in signal_results if getattr(r, "passed", False)]
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    summary = (
        f"Session {today} — {len(valid)} valid signal(s): "
        + (", ".join(r.ticker for r in valid) if valid else "none")
    )
    save_session_note(summary, verbose=True)

    return brief_path


# ── Capital state ─────────────────────────────────────────────────────────────

def _load_capital_pct() -> float:
    """Read last capital % from decisions-log.md (90-90-90 metric)."""
    if not LOG_PATH.exists():
        return 100.0
    lines = [l for l in LOG_PATH.read_text().split("\n") if l.startswith("| 20")]
    for line in reversed(lines):
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 8:
            try:
                return float(parts[7].replace("%", ""))
            except ValueError:
                pass
    return 100.0


def _build_brief_text(confirmed: list, apex_cleared: list) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if apex_cleared:
        parts = ", ".join(f"{r.ticker} {r.signal_type.value}" for r in apex_cleared)
    elif confirmed:
        parts = "No apex-cleared setups"
    else:
        parts = "No confirmed setups — all assets CONVERGING or FLAT"
    apex_blocked = [r.ticker for r in confirmed if r not in apex_cleared]
    if apex_blocked:
        parts += f" | Apex-blocked: {', '.join(apex_blocked)}"
    return f"Morning Brief {today} | {parts}"


# ── Pipeline summary ──────────────────────────────────────────────────────────

def _print_summary(
    signal_results: list,
    apex_cleared: list,
    orders: list[dict],
    publish_result: dict,
) -> None:
    confirmed = [r for r in signal_results if getattr(r, "passed", False)]
    blocked   = [r for r in signal_results if not getattr(r, "passed", False)]

    print(f"\n{'═'*58}")
    print(f"  PIPELINE COMPLETE — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'═'*58}")
    print(f"  Assets scanned:        {len(signal_results)}")
    print(f"  Signals confirmed:     {len(confirmed)}")
    print(f"  Signals blocked:       {len(blocked)}")
    print(f"  Apex-cleared:          {len(apex_cleared)}")
    print(f"  Orders staged:         {len(orders)}")
    print(f"  Published to AI-Trader:{publish_result.get('published', 0)}")
    print(f"  Morning brief posted:  {'✓' if publish_result.get('brief_posted') else '—'}")

    if confirmed:
        print("\n  Checklist-passed setups:")
        for r in confirmed:
            apex_tag = "apex ✓" if r in apex_cleared else "apex ✗"
            print(f"    [{apex_tag}] {r.ticker:<6} {r.signal_type.value:<5}  "
                  f"entry={r.entry_price:.4g}  stop={r.stop_loss:.4g}  "
                  f"target={r.target_1r:.4g}")
    else:
        print(f"\n  No valid setups — wait for confluence.")

    print(f"\n  Rules active: rules.md §1–4 | No stop = no signal")
    print(f"  Weekly bias confirmed. Check 4H at next candle close.")
    print(f"{'═'*58}\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="TradingVault Full Pipeline")
    parser.add_argument(
        "--account", type=float, default=None,
        help="Account balance for position sizing (e.g. --account 10000)",
    )
    parser.add_argument(
        "--no-research", action="store_true",
        help="Skip quant_mind_fetcher step (faster run)",
    )
    parser.add_argument(
        "--no-publish", action="store_true",
        help="Skip AI-Trader publish step",
    )
    parser.add_argument(
        "--rithmic-live", action="store_true",
        help="Submit Rithmic orders LIVE (default: dry-run staging only)",
    )
    args = parser.parse_args()

    print(f"\n{'═'*58}")
    print(f"  TRADINGVAULT — FULL PIPELINE")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    if args.account:
        print(f"  Account: ${args.account:,.2f}")
    print(f"{'═'*58}")

    # Gate: rules.md must exist
    if not RULES_PATH.exists():
        print(f"\n✗ BLOCKED: rules.md not found at {RULES_PATH}")
        print("  Session aborted — cannot proceed without Cockpit Checklist.")
        sys.exit(1)
    print(f"\n  ✓ rules.md loaded")

    # Gate: capital check
    capital_pct = _load_capital_pct()
    if capital_pct < 70:
        print(f"\n✗ STOP: Capital at {capital_pct:.1f}% — below 70% RED threshold.")
        print("  Full audit required before new signals. Session aborted.")
        sys.exit(1)
    print(f"  ✓ Capital: {capital_pct:.1f}%")

    # Step 1 — Research digest
    digest_path = None
    if not args.no_research:
        digest_path = step_1_research_digest()

    # Step 2 — NotebookLM
    nlm_results = step_2_notebooklm(digest_path)

    # Step 3 — OHLCV
    weekly_data = step_3_fetch_data()

    # Step 4 — Checklist
    signal_results = step_4_checklist(weekly_data, capital_pct)

    # Step 5 — Pattern DB
    step_5_pattern_db(signal_results)

    # Step 6 — Apex guard
    apex_cleared = step_6_apex_guard(signal_results)

    # Step 6b — Rithmic CME micro-futures (dry-run unless --rithmic-live)
    step_6b_rithmic(apex_cleared, live=args.rithmic_live)

    # Step 7 — Robinhood orders
    orders = step_7_robinhood(apex_cleared, args.account)

    # Step 8 — AI-Trader publish (apex-cleared only)
    publish_result: dict = {}
    if not args.no_publish:
        confirmed  = [r for r in signal_results if getattr(r, "passed", False)]
        brief_text = _build_brief_text(confirmed, apex_cleared)
        publish_result = step_8_publish(apex_cleared, brief_text)
    else:
        _banner(8, "AI-Trader Publisher — skipped (--no-publish)")

    # Step 9 — Log + Morning Brief
    step_9_log_and_brief(weekly_data, signal_results, nlm_results)

    # Final summary
    _print_summary(signal_results, apex_cleared, orders, publish_result)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Pipeline interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        print(f"\n✗ Pipeline error: {exc}")
        traceback.print_exc()
        sys.exit(1)
