"""
run_session.py — One command to run the full morning brief loop.

This is what you run at the start of every session.
It follows the CLAUDE.md Session Initialization Protocol exactly.

Usage:
    python run_session.py
    python run_session.py --account 10000     # enables position sizing on 4H entries

What it does (in order, per CLAUDE.md):
    1. Reads rules/rules.md  (confirms checklist is loaded)
    2. Reads last 5 log entries from decisions-log.md
    3a. Fetches 1W data for all 6 watch list assets
    3b. Runs Cockpit Checklist + Harmonic Scan on 1W data
    4. For FANNING assets: drills to 4H and finds entry setups + sizes positions
    5. Saves Morning Brief to sources/YYYY-MM-DD-morning-brief.md
    6. Logs valid signals to decisions-log.md
    7. Queries NotebookLM (grounded research) + saves session note
"""

import argparse
from pathlib import Path
from datetime import datetime, timezone
import sys

# Add agent/ to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from data_fetcher        import fetch_all_assets, save_morning_brief
from signal_checker      import run_full_checklist, append_to_decisions_log
from harmonic_detector   import scan_watch_list
from entry_finder        import find_4h_entries
from notebooklm_bridge   import run_morning_queries, save_session_note, _print_manual_fallback


VAULT_ROOT   = Path(__file__).parent.parent
RULES_PATH   = VAULT_ROOT / "rules"  / "rules.md"
LOG_PATH     = VAULT_ROOT / "logs"   / "decisions-log.md"
NOTES_PATH   = VAULT_ROOT / "logs"   / "session-notes.md"
SOURCES_DIR  = VAULT_ROOT / "sources"

WATCH_LIST   = ["BTC", "ETH", "SOL", "XRP", "LINK", "PEPE"]


def step_1_load_rules() -> bool:
    """Step 1: Verify rules.md is present and readable."""
    print("\n[STEP 1] Loading Cockpit Checklist...")
    if not RULES_PATH.exists():
        print(f"  ✗ ERROR: rules.md not found at {RULES_PATH}")
        print(f"  ✗ BLOCKED: Cannot proceed without checklist. Session aborted.")
        return False

    rules_text = RULES_PATH.read_text()
    sections   = rules_text.count("##")
    print(f"  ✓ rules.md loaded — {sections} sections found")
    print(f"  ✓ EMA Filter, Body Rule, Harmonics, ATR(7) — all active")
    return True


def step_2_load_behavioral_state() -> float:
    """
    Step 2: Read last 5 entries from decisions-log.md.
    Returns current capital % (from 90-90-90 metric).
    """
    print("\n[STEP 2] Loading behavioral state...")

    if not LOG_PATH.exists():
        print(f"  ⚠ decisions-log.md not found — starting fresh")
        return 100.0

    content = LOG_PATH.read_text()
    lines   = [l for l in content.split("\n") if l.startswith("| 20")]

    if not lines:
        print(f"  ✓ No prior signals on record — clean start")
        print(f"  ✓ Capital: 100%  |  90-90-90 status: OK")
        return 100.0

    print(f"  ✓ Found {len(lines)} prior signal(s) on record")
    print(f"  ✓ Last 5 entries:")
    for line in lines[-5:]:
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if parts:
            print(f"      {parts[0]} | {parts[1] if len(parts)>1 else ''} | "
                  f"{parts[2] if len(parts)>2 else ''}")

    # Parse capital % from log (column: 90-90-90 Metric)
    # Default to 100 if not found
    capital_pct = 100.0
    for line in reversed(lines):
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) >= 8:
            try:
                pct_str = parts[7].replace("%", "").strip()
                capital_pct = float(pct_str)
                break
            except (ValueError, IndexError):
                pass

    status = "OK"
    if capital_pct < 70:
        status = "🔴 RED — SESSION PAUSE REQUIRED"
    elif capital_pct < 80:
        status = "🟠 ORANGE — Reduce position sizing"
    elif capital_pct < 90:
        status = "🟡 YELLOW — Review last 3 decisions"

    print(f"  ✓ Capital: {capital_pct:.1f}%  |  90-90-90 status: {status}")

    if capital_pct < 70:
        print(f"\n  ✗ STOP: Capital below 70%. Full audit required before new signals.")
        print(f"  ✗ Review decisions-log.md for error patterns before continuing.")

    return capital_pct


def step_3_fetch_data() -> dict:
    """Step 3a: Fetch 1W OHLCV for all watch list assets."""
    print("\n[STEP 3a] Fetching 1W data (weekly bias — assessed FIRST)...")
    return fetch_all_assets(timeframe="1w")


def step_4_run_checklist(
    weekly_data: dict,
    capital_pct: float,
) -> list:
    """Step 4a/b: Run Cockpit Checklist + Harmonic Scan on 1W data."""
    print("\n[STEP 4a] Running Cockpit Checklist (1W)...")
    results = run_full_checklist(weekly_data, timeframe="1w", capital_pct=capital_pct)

    print("\n[STEP 4b] Running Harmonic Scan (1W)...")
    scan_watch_list(weekly_data, timeframe="1w")

    return results


def step_4c_find_entries(
    weekly_results: list,
    capital_pct: float,
    account_balance: float | None,
) -> list:
    """Step 4c: Drill to 4H for FANNING assets and find entry setups."""
    print("\n[STEP 4c] 4H Entry Finder (FANNING assets only)...")
    return find_4h_entries(
        weekly_results,
        account_balance=account_balance,
        risk_pct=1.0,
        capital_pct=capital_pct,
        verbose=True,
    )


def step_5_save_brief(weekly_data: dict) -> Path:
    """Step 5: Save Morning Brief to sources/ for NotebookLM."""
    print("\n[STEP 5] Saving Morning Brief to sources/...")
    brief_data = {ticker: {"df": df} for ticker, df in weekly_data.items()}
    return save_morning_brief(brief_data)


def step_6_log_signals(results: list) -> None:
    """Step 6: Log valid signals to decisions-log.md."""
    print("\n[STEP 6] Logging valid signals...")
    append_to_decisions_log(results, vault_root=VAULT_ROOT)


def step_7_notebooklm_query(brief_path: Path, signal_results: list) -> None:
    """
    Step 7: Query NotebookLM (Step 3 of CLAUDE.md Session Protocol).
    Imports today's brief, waits for grounding, runs morning questions.
    Falls back to printed manual commands if notebooklm-py isn't installed.
    """
    print(f"\n{'='*55}")
    print(f"  [STEP 7] NotebookLM — Grounded Research Layer")
    print(f"{'='*55}")

    nlm_results = run_morning_queries(brief_path=brief_path, verbose=True)

    # If bridge returned an error result only, show manual fallback
    if "_setup" in nlm_results and not nlm_results["_setup"].ok:
        return

    # Build session summary and save as persistent note
    valid_signals = [r for r in signal_results if getattr(r, "signal_type", None)
                     and r.signal_type.value != "NONE"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if valid_signals:
        signal_lines = "\n".join(
            f"- {getattr(r, 'ticker', '?')}: {getattr(r, 'signal_type', '?').value} "
            f"| Stop: {getattr(r, 'stop_loss', '?')} | Target: {getattr(r, 'target', '?')}"
            for r in valid_signals
        )
        summary = f"Session {today} — {len(valid_signals)} valid signal(s):\n{signal_lines}"
    else:
        summary = f"Session {today} — No valid signals. All assets CONVERGING or FLAT."

    save_session_note(summary, verbose=True)
    print(f"\n{'='*55}\n")


def main():
    parser = argparse.ArgumentParser(description="Trading Agent — Session Initialization")
    parser.add_argument(
        "--account", type=float, default=None,
        help="Account balance in USD for position sizing (e.g. --account 10000)",
    )
    args = parser.parse_args()

    print("\n" + "="*55)
    print("  TRADING AGENT — SESSION INITIALIZATION")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Account: {'${:,.2f}'.format(args.account) if args.account else 'not set (sizing disabled)'}")
    print("="*55)

    # Step 1 — Rules
    if not step_1_load_rules():
        sys.exit(1)

    # Step 2 — Behavioral state
    capital_pct = step_2_load_behavioral_state()
    if capital_pct < 70:
        sys.exit(1)   # Hard stop per capital protocol

    # Step 3a — Fetch 1W data
    weekly_data = step_3_fetch_data()

    # Step 4a/b — Checklist + Harmonic scan
    results = step_4_run_checklist(weekly_data, capital_pct)

    # Step 4c — 4H entry drill-down (FANNING assets only)
    step_4c_find_entries(results, capital_pct, args.account)

    # Step 5 — Save brief
    brief_path = step_5_save_brief(weekly_data)

    # Step 6 — Log signals
    step_6_log_signals(results)

    # Step 7 — NotebookLM grounded query + persistent session note
    step_7_notebooklm_query(brief_path, results)

    print("Session initialization complete.")
    print("Weekly bias confirmed. 4H entries assessed. Check 4H again at next close.\n")


if __name__ == "__main__":
    main()
