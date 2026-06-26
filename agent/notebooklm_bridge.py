"""
notebooklm_bridge.py — Programmatic wrapper around the notebooklm-py CLI.

Provides simple sync functions for run_session.py Step 3 so queries happen
inside the session loop rather than requiring manual terminal commands.

Install:  pip install notebooklm-py
Auth:     notebooklm login          (once — stored in ~/.notebooklm/)
Notebook: Green Bread Coach(GBC) — ID used directly for all CLI calls.

All functions return a BridgeResult so callers can degrade gracefully when
notebooklm-py is not installed or the user hasn't authenticated yet.
"""

import json
import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


NOTEBOOK    = "Green Bread Coach(GBC)"
NOTEBOOK_ID = os.environ.get(
    "NOTEBOOKLM_NOTEBOOK_ID",
    "57880976-bb78-4efc-9272-de4b83b25358",
)
_CLI = "notebooklm"

# Always pass notebook ID via -n — never rely on name lookup or `notebooklm use`.
_NB = NOTEBOOK_ID


@dataclass
class BridgeResult:
    ok:     bool
    output: str
    error:  str = ""

    def __str__(self) -> str:
        return self.output if self.ok else f"[ERROR] {self.error}"


def _available() -> bool:
    return shutil.which(_CLI) is not None


def _authenticated() -> bool:
    """Return True if notebooklm-py has valid stored credentials."""
    if not _available():
        return False
    try:
        proc = subprocess.run(
            [_CLI, "auth", "check", "--test", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(proc.stdout)
        return data.get("status") == "ok"
    except Exception:
        return False


def _run(*args: str, timeout: int = 120) -> BridgeResult:
    """Run a notebooklm CLI command, return structured result."""
    if not _available():
        return BridgeResult(
            ok=False,
            output="",
            error=(
                "notebooklm-py not installed. "
                "Run: pip install notebooklm-py  then  notebooklm login"
            ),
        )
    cmd = [_CLI, *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return BridgeResult(ok=True, output=proc.stdout.strip())
        return BridgeResult(ok=False, output=proc.stdout.strip(), error=proc.stderr.strip())
    except subprocess.TimeoutExpired:
        return BridgeResult(ok=False, output="", error=f"Command timed out after {timeout}s")
    except Exception as exc:
        return BridgeResult(ok=False, output="", error=str(exc))


def _parse_source_id(json_output: str) -> Optional[str]:
    """Extract source ID from `source add --json` response."""
    try:
        data = json.loads(json_output)
    except (json.JSONDecodeError, TypeError):
        return None
    source = data.get("source")
    if isinstance(source, dict) and source.get("id"):
        return str(source["id"])
    if data.get("id"):
        return str(data["id"])
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def source_add(path: Path, notebook_id: str = _NB) -> BridgeResult:
    """Add a local file as a source. Returns JSON output containing source ID."""
    return _run("source", "add", str(path), "-n", notebook_id, "--json")


def source_wait(source_id: str, notebook_id: str = _NB) -> BridgeResult:
    """Wait for a specific source to finish processing."""
    return _run("source", "wait", source_id, "-n", notebook_id, timeout=300)


def ask(question: str, notebook_id: str = _NB) -> BridgeResult:
    """Ask a grounded question; answers cite your notebook sources."""
    return _run("ask", question, "-n", notebook_id, timeout=120)


def note_create(text: str, title: str, notebook_id: str = _NB) -> BridgeResult:
    """
    Persist a session note for cross-session recall.

    CLI syntax: notebooklm note create "<content>" -t "<title>" -n <notebook_id>
    """
    return _run("note", "create", text, "-t", title, "-n", notebook_id)


# ── Session Step 3 — Morning Brief query sequence ────────────────────────────

MORNING_QUESTIONS = [
    "Summarize the macro market context. What are the key themes right now?",
    "Which assets on my watch list have the cleanest EMA fan setup?",
    "What does my strategy say about CONVERGING assets on the weekly chart?",
    "Are there any central bank events or macro risk events this week?",
]


def run_morning_queries(
    brief_path: Optional[Path] = None,
    notebook: str = NOTEBOOK,
    verbose: bool = True,
) -> dict[str, BridgeResult]:
    """
    Run the full Step 3 sequence:
      1. Import today's morning brief (if path provided)
      2. Wait for source processing (by source ID)
      3. Ask all morning questions
    Returns a dict of {question: BridgeResult}.
    """
    results: dict[str, BridgeResult] = {}

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log(f"\n[STEP 3] Querying NotebookLM — {notebook}")
    log(f"  Notebook ID: {_NB}")

    if not _available():
        r = BridgeResult(
            ok=False, output="",
            error="notebooklm-py not installed. Run: pip install notebooklm-py",
        )
        log(f"  ✗ {r.error}")
        _print_manual_fallback(brief_path)
        return {"_setup": r}

    if not _authenticated():
        r = BridgeResult(
            ok=False, output="",
            error=(
                "NotebookLM not authenticated. Run:  notebooklm login\n"
                "  Then re-run this session to enable grounded research."
            ),
        )
        log(f"  ✗ {r.error}")
        _print_manual_fallback(brief_path)
        return {"_setup": r}

    log(f"  ✓ Authenticated — using notebook ID {_NB[:8]}...")

    # 1. Add morning brief source
    if brief_path and brief_path.exists():
        log(f"  → Adding source: {brief_path.name}")
        r = source_add(brief_path)
        if r.ok:
            log("  ✓ Source added")
            source_id = _parse_source_id(r.output)
            if source_id:
                log(f"  → Waiting for source {source_id[:12]}...")
                rw = source_wait(source_id)
                if rw.ok:
                    log("  ✓ Source grounded")
                else:
                    log(f"  ⚠ source wait failed (may still work): {rw.error}")
            else:
                log(f"  ⚠ Could not parse source ID from: {r.output[:120]}")
        else:
            log(f"  ⚠ Source add failed (continuing): {r.error}")

    # 2. Ask all morning questions
    log("\n  [NotebookLM Responses]")
    for q in MORNING_QUESTIONS:
        log(f"\n  Q: {q}")
        r = ask(q)
        results[q] = r
        if r.ok:
            for line in r.output.split("\n"):
                log(f"     {line}")
        else:
            log(f"  ✗ {r.error}")

    return results


def save_session_note(
    summary: str,
    notebook: str = NOTEBOOK,
    verbose: bool = True,
) -> BridgeResult:
    """
    Persist today's session summary as a NotebookLM note
    (cross-session memory on Google's infrastructure).
    """
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Session {today}"

    if verbose:
        print(f"\n  → Saving session note: '{title}'")

    r = note_create(text=summary, title=title)
    if verbose:
        if r.ok:
            print(f"  ✓ Session note saved to '{notebook}' ({_NB[:8]}...)")
        else:
            print(f"  ✗ Note save failed: {r.error}")
    return r


# ── Fallback — print manual commands ─────────────────────────────────────────

def _print_manual_fallback(brief_path: Optional[Path] = None) -> None:
    """Print CLI commands for the user to run manually (METHOD B from CLAUDE.md)."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("\n  ── Manual fallback (METHOD B) ──────────────────────")
    if brief_path:
        print(f"  notebooklm source add {brief_path} -n {_NB} --json")
        print(f"  notebooklm source wait <SOURCE_ID> -n {_NB}")
    for q in MORNING_QUESTIONS:
        print(f"  notebooklm ask '{q}' -n {_NB}")
    print(f"  notebooklm note create '<summary>' -t 'Session {today}' -n {_NB}")
    print("  ────────────────────────────────────────────────────\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if not _available():
        print("notebooklm-py is not installed.")
        print("Run:  pip install notebooklm-py")
        print("Then: notebooklm login")
        sys.exit(1)

    print(f"notebooklm-py detected at: {shutil.which(_CLI)}")
    print(f"Notebook: {NOTEBOOK}")
    print(f"Notebook ID: {_NB}")
    print()

    r = ask("What is the main purpose of this notebook?")
    if r.ok:
        print("Connection OK:")
        print(r.output[:500])
    else:
        print(f"Connection failed: {r.error}")
        print("Run: notebooklm login")
        sys.exit(1)
