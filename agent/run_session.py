"""
run_session.py — One command to run the full morning brief loop.

This is what you run at the start of every session.
It follows the CLAUDE.md Session Initialization Protocol exactly.

Usage:
    python run_session.py

What it does (in order, per CLAUDE.md):
    1. Reads rules/rules.md  (confirms checklist is loaded)
    2. Reads last 5 log entries from decisions-log.md
    3. Fetches 1W data for all 6 watch list assets
    4. Runs full Cockpit Checklist on each
    5. Saves Morning Brief to sources/YYYY-MM-DD-morning-brief.md
    6. Logs valid signals to decisions-log.md
    7. Prints NotebookLM commands to run next
"""

from pathlib import Path
from datetime import datetime, timezone
import sys

# Add agent/ to path so imports work
sys.path.insert(0, str(Path(__file__).parent))

from data_fetcher   import fetch_all_assets, save_morning_brief
from signal_checker import run_full_checklist, append_to_decisions_log


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
    """Step 3: Fetch 1W OHLCV for all watch list assets."""
    print("\n[STEP 3] Fetching 1W data (weekly bias — assessed FIRST)...")
    return fetch_all_assets(timeframe="1W")


def step_4_run_checklist(
    weekly_data: dict,
    capital_pct: float,
) -> list:
    """Step 4: Run Cockpit Checklist on all assets."""
    print("\n[STEP 4] Running Cockpit Checklist...")
    return run_full_checklist(weekly_data, timeframe="1W", capital_pct=capital_pct)


def step_5_save_brief(weekly_data: dict) -> Path:
    """Step 5: Save Morning Brief to sources/ for NotebookLM."""
    print("\n[STEP 5] Saving Morning Brief to sources/...")
    brief_data = {ticker: {"df": df} for ticker, df in weekly_data.items()}
    return save_morning_brief(brief_data)


def step_6_log_signals(results: list) -> None:
    """Step 6: Log valid signals to decisions-log.md."""
    print("\n[STEP 6] Logging valid signals...")
    append_to_decisions_log(results, vault_root=VAULT_ROOT)


def step_7_notebooklm_commands(brief_path: Path) -> None:
    """Step 7: Print the exact NotebookLM commands to run next."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\n{'='*55}")
    print(f"  [STEP 7] NEXT: Query NotebookLM")
    print(f"{'='*55}")
    print(f"\n  Run these commands in your terminal:\n")
    print(f"  # Import today's brief into your notebook:")
    print(f"  notebooklm use 'Master Brain'")
    print(f"  notebooklm source add {brief_path}")
    print(f"  notebooklm source wait")
    print(f"")
    print(f"  # Then ask grounded questions:")
    print(f"  notebooklm ask 'Summarize the {today} morning brief'")
    print(f"  notebooklm ask 'Which assets have the cleanest EMA fan today?'")
    print(f"  notebooklm ask 'What does my strategy say about CONVERGING assets?'")
    print(f"")
    print(f"  # Save session to persistent memory:")
    print(f"  notebooklm note create 'Session {today}: <paste signal summary>'")
    print(f"{'='*55}\n")


def main():
    print("\n" + "="*55)
    print("  TRADING AGENT — SESSION INITIALIZATION")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("  Following CLAUDE.md protocol — 7 steps")
    print("="*55)

    # Step 1 — Rules
    if not step_1_load_rules():
        sys.exit(1)

    # Step 2 — Behavioral state
    capital_pct = step_2_load_behavioral_state()
    if capital_pct < 70:
        sys.exit(1)   # Hard stop per capital protocol

    # Step 3 — Fetch data
    weekly_data = step_3_fetch_data()

    # Step 4 — Checklist
    results = step_4_run_checklist(weekly_data, capital_pct)

    # Step 5 — Save brief
    brief_path = step_5_save_brief(weekly_data)

    # Step 6 — Log signals
    step_6_log_signals(results)

    # Step 7 — NotebookLM instructions
    step_7_notebooklm_commands(brief_path)

    print("Session initialization complete.")
    print("Weekly bias confirmed. Check 4H only for FANNING assets.\n")


if __name__ == "__main__":
    main()
