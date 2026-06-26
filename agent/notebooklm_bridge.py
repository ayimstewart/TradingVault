"""
notebooklm_bridge.py — Programmatic wrapper around the notebooklm-py CLI.

Provides simple sync functions for run_session.py Step 3 so queries happen
inside the session loop rather than requiring manual terminal commands.

Install:  pip install notebooklm-py
Auth:     notebooklm login          (once — stored in ~/.notebooklm/)
Notebook: Set NOTEBOOKLM_NOTEBOOK env var or pass notebook= to each call.

All functions return a BridgeResult so callers can degrade gracefully when
notebooklm-py is not installed or the user hasn't authenticated yet.
"""

import os
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


NOTEBOOK    = os.environ.get("NOTEBOOKLM_NOTEBOOK", "Green Bread Coach(GBC)")
NOTEBOOK_ID = os.environ.get("NOTEBOOKLM_NOTEBOOK_ID", "57880976-bb78-4efc-9272-de4b83b25358")
_CLI        = "notebooklm"

# Use ID for all CLI calls — name lookup is unreliable with multi-word names.
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
        import json as _json
        data = _json.loads(proc.stdout)
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


# ── Public API ────────────────────────────────────────────────────────────────

def use_notebook(notebook_id: str = _NB) -> BridgeResult:
    """Set the active notebook context by ID."""
    return _run("use", notebook_id)


def source_add(
    path: Path,
    notebook_id: str = _NB,
) -> BridgeResult:
    """Add a local file as a source. Returns JSON output containing source ID."""
    return _run("source", "add", str(path), "-n", notebook_id, "--json")


def source_wait(source_id: str, notebook_id: str = _NB) -> BridgeResult:
    """Wait for a specific source to finish processing (requires source ID from source_add)."""
    return _run("source", "wait", source_id, "-n", notebook_id, timeout=300)


def ask(question: str, notebook_id: str = _NB) -> BridgeResult:
    """Ask a grounded question; answers cite your notebook sources."""
    return _run("ask", question, "-n", notebook_id, timeout=120)


def note_create(title: str, text: str, notebook_id: str = _NB) -> BridgeResult:
    """Persist a session note for cross-session recall."""
    # Correct syntax: notebooklm note create <content> -t <title> -n <id>
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
      1. Set active notebook (by ID)
      2. Import today's morning brief (if path provided)
      3. Wait for source processing
      4. Ask all morning questions
    Returns a dict of {question: BridgeResult}.
    """
    results: dict[str, BridgeResult] = {}

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log(f"\n[STEP 3] Querying NotebookLM — {notebook} ({_NB})")

    # 0. Check auth before attempting any CLI calls
    if not _available():
        r = BridgeResult(ok=False, output="", error="notebooklm-py not installed. Run: pip install notebooklm-py")
        log(f"  ✗ {r.error}")
        _print_manual_fallback(brief_path)
        return {"_setup": r}

    if not _authenticated():
        r = BridgeResult(ok=False, output="", error=(
            "NotebookLM not authenticated. Run:  notebooklm login\n"
            "  Then re-run this session to enable grounded research."
        ))
        log(f"  ✗ {r.error}")
        _print_manual_fallback(brief_path)
        return {"_setup": r}

    # 1. Activate notebook by ID
    r = use_notebook()
    if not r.ok:
        log(f"  ✗ Could not activate notebook {_NB}: {r.error}")
        log(f"  → Fallback: run these manually:")
        _print_manual_fallback(brief_path)
        return {"_setup": r}

    log(f"  ✓ Notebook active: {notebook}")

    # 2. Add morning brief source
    if brief_path and brief_path.exists():
        log(f"  → Adding source: {brief_path.name}")
        r = source_add(brief_path)
        if r.ok:
            log(f"  ✓ Source added")
            # 3. Wait for grounding using source ID from JSON response
            try:
                import json as _json
                source_id = _json.loads(r.output)["source"]["id"]
                log(f"  → Waiting for source {source_id[:8]}... to process")
                r = source_wait(source_id)
                if r.ok:
                    log(f"  ✓ Source grounded")
                else:
                    log(f"  ⚠ source wait failed (may still work): {r.error}")
            except (KeyError, ValueError, Exception) as e:
                log(f"  ⚠ Could not parse source ID — skipping wait: {e}")
        else:
            log(f"  ⚠ Source add failed (continuing): {r.error}")

    # 4. Ask all morning questions
    log(f"\n  [NotebookLM Responses]")
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

    r = note_create(title, summary)
    if verbose:
        if r.ok:
            print(f"  ✓ Session note saved to '{notebook}'")
        else:
            print(f"  ✗ Note save failed: {r.error}")
    return r


# ── Fallback — print manual commands ─────────────────────────────────────────

def _print_manual_fallback(brief_path: Optional[Path] = None) -> None:
    """Print CLI commands for the user to run manually (METHOD B from CLAUDE.md)."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\n  ── Manual fallback (METHOD B) ──────────────────────")
    print(f"  notebooklm use {_NB}")
    if brief_path:
        print(f"  notebooklm source add {brief_path} -n {_NB}")
        print(f"  notebooklm source wait -n {_NB}")
    for q in MORNING_QUESTIONS:
        print(f"  notebooklm ask '{q}' -n {_NB}")
    print(f"  notebooklm note create '<paste summary here>' -t 'Session {today}' -n {_NB}")
    print(f"  ────────────────────────────────────────────────────\n")


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if not _available():
        print("notebooklm-py is not installed.")
        print("Run:  pip install notebooklm-py")
        print("Then: notebooklm login")
        sys.exit(1)

    print(f"notebooklm-py detected at: {shutil.which(_CLI)}")
    print(f"Active notebook: {NOTEBOOK} ({_NB})")
    print()

    # Quick connectivity test (use ID, not name)
    r = ask("What is the main purpose of this notebook?")
    if r.ok:
        print("Connection OK:")
        print(r.output[:500])
    else:
        print(f"Connection failed: {r.error}")
        print("Run: notebooklm login")
        sys.exit(1)
