"""
morning_brief_auto.py — Scheduled daily morning brief for the trading agent.

Installs a macOS launchd plist that runs run_session.py every morning at 07:00 UTC
(before US pre-market and London open). The job runs even when the terminal is closed.

Usage:
    python3 morning_brief_auto.py install     # install launchd job
    python3 morning_brief_auto.py uninstall   # remove launchd job
    python3 morning_brief_auto.py status      # check if job is loaded
    python3 morning_brief_auto.py run         # run now (same as run_session.py)

Logs land in:
    logs/morning-brief-auto.log    (stdout)
    logs/morning-brief-auto-err.log (stderr)

To change the run time: edit HOUR_UTC / MINUTE_UTC and re-run `install`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_ROOT  = Path(__file__).parent.parent
AGENT_DIR   = Path(__file__).parent
LOG_DIR     = VAULT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

STDOUT_LOG  = LOG_DIR / "morning-brief-auto.log"
STDERR_LOG  = LOG_DIR / "morning-brief-auto-err.log"

# ── Schedule ──────────────────────────────────────────────────────────────────
HOUR_UTC   = 7    # 07:00 UTC = ~03:00 ET  (pre-market, before London open)
MINUTE_UTC = 0

# ── launchd identity ──────────────────────────────────────────────────────────
LABEL         = "com.tradingvault.morningbrief"
PLIST_PATH    = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PYTHON        = sys.executable
SESSION_SCRIPT = str(AGENT_DIR / "run_session.py")


def _plist_content() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{SESSION_SCRIPT}</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{HOUR_UTC}</integer>
        <key>Minute</key>
        <integer>{MINUTE_UTC}</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>{STDOUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>{STDERR_LOG}</string>

    <key>WorkingDirectory</key>
    <string>{VAULT_ROOT}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}</string>
        <key>PYTHONPATH</key>
        <string>{str(AGENT_DIR)}</string>
    </dict>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def install() -> None:
    """Write plist and load with launchctl."""
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_plist_content())
    print(f"✓ Plist written: {PLIST_PATH}")

    # Unload first in case it was previously loaded
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)

    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"✓ Job loaded: {LABEL}")
        print(f"  Schedule:  {HOUR_UTC:02d}:{MINUTE_UTC:02d} UTC daily")
        print(f"  Stdout:    {STDOUT_LOG}")
        print(f"  Stderr:    {STDERR_LOG}")
        print(f"\n  To check status: python3 morning_brief_auto.py status")
        print(f"  To remove:       python3 morning_brief_auto.py uninstall")
    else:
        print(f"✗ launchctl load failed: {result.stderr.strip()}")
        sys.exit(1)


def uninstall() -> None:
    """Unload and remove the plist."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        print(f"✓ Job removed: {LABEL}")
    else:
        print(f"  Job not installed (plist not found at {PLIST_PATH})")


def status() -> None:
    """Print current status of the launchd job."""
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"✓ Job is LOADED: {LABEL}")
        print(f"  Schedule: {HOUR_UTC:02d}:{MINUTE_UTC:02d} UTC daily")
        print(f"  Plist:    {PLIST_PATH}")
        if STDOUT_LOG.exists():
            size = STDOUT_LOG.stat().st_size
            mtime = datetime.fromtimestamp(STDOUT_LOG.stat().st_mtime, tz=timezone.utc)
            print(f"  Log:      {STDOUT_LOG} ({size:,} bytes, last run: {mtime.strftime('%Y-%m-%d %H:%M UTC')})")
        else:
            print(f"  Log:      {STDOUT_LOG} (not yet created — job hasn't run)")
    else:
        print(f"  Job NOT loaded: {LABEL}")
        if PLIST_PATH.exists():
            print(f"  Plist exists at {PLIST_PATH} but is not loaded.")
            print(f"  Run: python3 morning_brief_auto.py install")
        else:
            print(f"  Run: python3 morning_brief_auto.py install")


def run_now() -> None:
    """Trigger a session run immediately."""
    print(f"Running session now — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_session", SESSION_SCRIPT)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


# ── CLI ───────────────────────────────────────────────────────────────────────

COMMANDS = {
    "install":   install,
    "uninstall": uninstall,
    "status":    status,
    "run":       run_now,
}

if __name__ == "__main__":
    if sys.platform != "darwin":
        print("morning_brief_auto.py — macOS launchd scheduler")
        print("On Linux/Windows: add a cron job or Task Scheduler entry pointing to:")
        print(f"  {PYTHON} {SESSION_SCRIPT}")
        sys.exit(0)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd not in COMMANDS:
        print(f"Usage: python3 morning_brief_auto.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)

    COMMANDS[cmd]()
