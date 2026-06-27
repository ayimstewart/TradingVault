"""
llmwiki_sync.py — Auto-update LLM Wiki from new vault sources.

Every time a new morning brief, backtest result, or analysis is saved to
sources/, this module syncs it into the LLMWiki knowledge graph so the
agent's second brain stays current without manual effort.

How it works:
  1. Scan sources/ for files newer than last sync timestamp
  2. Check if LLMWiki is running at localhost:8000 (from llmwiki open ~/vault)
  3. POST each new file to the LLMWiki ingest API
  4. Save last-sync timestamp to .llmwiki-sync-state.json

Usage:
    python3 llmwiki_sync.py                 # sync new files since last run
    python3 llmwiki_sync.py --status        # show sync state + LLMWiki status
    python3 llmwiki_sync.py --force         # re-sync all sources (full rebuild)
    python3 llmwiki_sync.py --dry-run       # show what would sync, don't upload

LLMWiki must be running:
    cd references/llmwiki && ./llmwiki open /path/to/TradingVault/sources

MCP alternative (if llmwiki MCP is wired into Claude Code):
    The MCP tools (read, create, search) can be called directly from Claude
    Code sessions without this script. This script handles autonomous/scheduled
    syncing between sessions.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VAULT_ROOT  = Path(__file__).parent.parent
SOURCES_DIR = VAULT_ROOT / "sources"
STATE_FILE  = VAULT_ROOT / ".llmwiki-sync-state.json"

LLMWIKI_URL = "http://localhost:8000"   # default port from llmwiki open
TIMEOUT_S   = 15


# ── HTTP helper (no extra deps — stdlib urllib) ───────────────────────────────

def _get(path: str) -> Optional[dict]:
    """GET from LLMWiki API. Returns parsed JSON or None on error."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen(f"{LLMWIKI_URL}{path}", timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError:
        return None
    except Exception:
        return None


def _post_file(file_path: Path) -> Optional[dict]:
    """
    POST a markdown file to LLMWiki as a new source document.
    LLMWiki picks it up via its watcher, but this forces immediate indexing.
    """
    import urllib.request
    import urllib.error

    # LLMWiki watches its workspace folder directly; copying the file is enough
    # when the workspace is pointing at sources/. If the workspace is the vault
    # root, dropping files in sources/ triggers auto-index. We'll also POST to
    # the REST ingest endpoint if it's available.

    try:
        boundary = f"----FormBoundary{int(time.time())}"
        file_content = file_path.read_bytes()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
        ).encode() + file_content + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{LLMWIKI_URL}/v1/upload",
            data=body,
            method="POST",
        )
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")

        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError:
        return None
    except Exception:
        return None


# ── State management ──────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_sync": 0.0, "synced_files": []}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── LLMWiki availability ──────────────────────────────────────────────────────

def _llmwiki_running() -> bool:
    """Return True if LLMWiki API is reachable at localhost:8000."""
    result = _get("/health")
    return result is not None


# ── Core sync logic ───────────────────────────────────────────────────────────

def get_new_sources(since_ts: float = 0.0) -> list[Path]:
    """
    Return source files in sources/ that are newer than since_ts.
    Ordered oldest-first so the wiki builds chronologically.
    """
    if not SOURCES_DIR.exists():
        return []

    files = sorted(
        [f for f in SOURCES_DIR.glob("**/*.md") if f.is_file()],
        key=lambda f: f.stat().st_mtime,
    )
    if since_ts > 0:
        files = [f for f in files if f.stat().st_mtime > since_ts]
    return files


def sync(
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
) -> dict[str, str]:
    """
    Sync new sources to LLMWiki.

    Returns a dict of {filename: "synced" | "skipped" | "error"}.
    """
    state   = _load_state()
    since   = 0.0 if force else state.get("last_sync", 0.0)
    results = {}

    new_files = get_new_sources(since_ts=since)

    if verbose:
        print(f"\n{'='*55}")
        print(f"  LLMWIKI SYNC — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"{'='*55}")
        print(f"  Sources dir:  {SOURCES_DIR}")
        print(f"  Since:        {'all files' if force else datetime.fromtimestamp(since, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')}")
        print(f"  New files:    {len(new_files)}")

    if not new_files:
        if verbose:
            print(f"  ✓ Nothing to sync — already up to date")
        return results

    running = _llmwiki_running()
    if verbose:
        status = "ONLINE" if running else "OFFLINE"
        print(f"  LLMWiki API:  {LLMWIKI_URL}  [{status}]")

    for file_path in new_files:
        rel = file_path.relative_to(VAULT_ROOT)
        if dry_run:
            if verbose:
                print(f"  [DRY-RUN] Would sync: {rel}")
            results[str(rel)] = "dry-run"
            continue

        if running:
            resp = _post_file(file_path)
            if resp is not None:
                results[str(rel)] = "synced"
                if verbose:
                    print(f"  ✓ Synced:  {rel}")
            else:
                # File is in sources/ — LLMWiki watcher picks it up automatically
                # if workspace is pointed at vault root. Mark as pending.
                results[str(rel)] = "pending-watcher"
                if verbose:
                    print(f"  ~ Pending: {rel} (LLMWiki watcher will index)")
        else:
            # LLMWiki is offline — queue for next run
            results[str(rel)] = "queued"
            if verbose:
                print(f"  ⏸ Queued:  {rel} (LLMWiki offline — start with: ./llmwiki open {VAULT_ROOT})")

    if not dry_run:
        state["last_sync"]    = time.time()
        state["synced_files"] = sorted(set(
            state.get("synced_files", []) +
            [str(f.relative_to(VAULT_ROOT)) for f in new_files]
        ))
        _save_state(state)

    if verbose:
        synced  = sum(1 for v in results.values() if v == "synced")
        pending = sum(1 for v in results.values() if "pending" in v or "queued" in v)
        print(f"\n  Done: {synced} synced, {pending} pending/queued")
        if not running:
            print(f"\n  To start LLMWiki:")
            print(f"    cd {VAULT_ROOT}/references/llmwiki")
            print(f"    ./llmwiki open {VAULT_ROOT}")
        print(f"{'='*55}\n")

    return results


def print_status() -> None:
    """Print sync state and LLMWiki availability."""
    state   = _load_state()
    running = _llmwiki_running()
    all_src = get_new_sources(since_ts=0.0)
    new_src = get_new_sources(since_ts=state.get("last_sync", 0.0))

    print(f"\n{'='*55}")
    print(f"  LLMWIKI SYNC STATUS")
    print(f"{'='*55}")
    print(f"  LLMWiki API:  {LLMWIKI_URL}  [{'ONLINE' if running else 'OFFLINE'}]")
    print(f"  Sources dir:  {SOURCES_DIR}  ({len(all_src)} files total)")

    last = state.get("last_sync", 0.0)
    if last:
        dt = datetime.fromtimestamp(last, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print(f"  Last sync:    {dt}")
    else:
        print(f"  Last sync:    never")

    print(f"  New since:    {len(new_src)} file(s) pending")

    if new_src:
        print(f"\n  Pending files:")
        for f in new_src[-5:]:
            print(f"    · {f.name}")
        if len(new_src) > 5:
            print(f"    ... and {len(new_src)-5} more")

    if not running:
        print(f"\n  Start LLMWiki:")
        print(f"    cd {VAULT_ROOT}/references/llmwiki")
        print(f"    ./llmwiki open {VAULT_ROOT}")
    print(f"{'='*55}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLMWiki Sync — vault sources → knowledge graph")
    parser.add_argument("--status",  action="store_true", help="Show sync state")
    parser.add_argument("--force",   action="store_true", help="Re-sync all files")
    parser.add_argument("--dry-run", action="store_true", help="Show what would sync")
    args = parser.parse_args()

    if args.status:
        print_status()
    else:
        sync(force=args.force, dry_run=args.dry_run, verbose=True)
