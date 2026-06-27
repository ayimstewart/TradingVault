"""
ai_trader_publisher.py — Pipeline step: publish confirmed signals to AI-Trader.

Registers on ai4trade.ai, publishes checklist-approved signals, posts the
morning brief as a strategy post, and runs a single heartbeat check per
pipeline execution.

Token: ~/.tradingvault/ai_trader_token.json
       (bridge config ~/.tradingvault/ai_trader.json kept in sync)

Usage (standalone):
    python3 ai_trader_publisher.py setup       # register or login
    python3 ai_trader_publisher.py status      # account info
    python3 ai_trader_publisher.py heartbeat   # single heartbeat poll
    python3 ai_trader_publisher.py feed        # recent signal feed

Pipeline usage (from full_pipeline.py):
    from ai_trader_publisher import run_pipeline_step
    result = run_pipeline_step(signal_results, brief_text, watch_list)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL    = "https://ai4trade.ai/api"
CONFIG_DIR  = Path.home() / ".tradingvault"
TOKEN_FILE  = CONFIG_DIR / "ai_trader_token.json"  # canonical path for this script
BRIDGE_FILE = CONFIG_DIR / "ai_trader.json"         # bridge config — kept in sync

AGENT_NAME  = "TradingVault"
AGENT_EMAIL = os.environ.get("AI_TRADER_EMAIL", "stewartankrah05@gmail.com")


def _load_token() -> Optional[str]:
    """Load token from TOKEN_FILE, falling back to BRIDGE_FILE."""
    for path in (TOKEN_FILE, BRIDGE_FILE):
        if path.exists():
            try:
                return json.loads(path.read_text()).get("token")
            except Exception:
                pass
    return None


def _save_token(token: str, agent_id: Optional[int] = None) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "token":    token,
        "agent_id": agent_id,
        "email":    AGENT_EMAIL,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    TOKEN_FILE.chmod(0o600)

    # Keep bridge config in sync so ai_trader_bridge.py also works
    existing: dict = {}
    if BRIDGE_FILE.exists():
        try:
            existing = json.loads(BRIDGE_FILE.read_text())
        except Exception:
            pass
    existing.update({"token": token, "agent_id": agent_id, "email": AGENT_EMAIL})
    BRIDGE_FILE.write_text(json.dumps(existing, indent=2))
    BRIDGE_FILE.chmod(0o600)


def _headers() -> dict:
    token = _load_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


# ── Auth ──────────────────────────────────────────────────────────────────────

def register(password: str) -> dict:
    """Create a new agent account and save token."""
    resp = requests.post(f"{BASE_URL}/claw/agents/selfRegister", json={
        "name":     AGENT_NAME,
        "email":    AGENT_EMAIL,
        "password": password,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("token"):
        _save_token(data["token"], data.get("agent_id"))
        print(f"  ✓ Registered: {AGENT_NAME} (agent_id: {data.get('agent_id')})")
        print(f"  ✓ Token saved: {TOKEN_FILE}")
    return data


def login(password: str) -> dict:
    """Login to existing account and refresh stored token."""
    resp = requests.post(f"{BASE_URL}/claw/agents/login", json={
        "email":    AGENT_EMAIL,
        "password": password,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("token"):
        _save_token(data["token"], data.get("agent_id"))
        print(f"  ✓ Logged in — token refreshed: {TOKEN_FILE}")
    return data


# ── Publishing ────────────────────────────────────────────────────────────────

def publish_confirmed_signals(signal_results: list, note: str = "") -> list[dict]:
    """
    Publish all checklist-passed signals to AI-Trader as realtime crypto trades.
    Blocked signals are silently skipped.

    Returns list of API responses for each successfully published signal.
    """
    published: list[dict] = []

    for sig in signal_results:
        if not getattr(sig, "passed", False):
            continue

        stop = float(getattr(sig, "stop_loss", 0.0) or 0.0)
        if stop <= 0:
            print(f"  ✗ BLOCKED {sig.ticker}: No ATR(7) stop — not publishing (rules.md §4)")
            continue

        entry = float(getattr(sig, "entry_price", 0.0) or 0.0)
        if entry <= 0:
            print(f"  ✗ BLOCKED {sig.ticker}: No entry price — not publishing")
            continue

        direction = sig.signal_type.value   # "LONG" | "SHORT"
        action    = "buy" if direction == "LONG" else "short"

        parts = [
            f"{sig.ticker} {direction}",
            f"Entry: {entry:.6g}",
            f"Stop (ATR7): {stop:.6g}",
            f"Target 1R: {sig.target_1r:.6g}",
            f"EMA: {sig.ema_trend}",
            f"TF: {sig.timeframe.upper()}",
        ]
        if note:
            parts.append(note)

        payload = {
            "market":      "crypto",
            "action":      action,
            "symbol":      sig.ticker,
            "price":       entry,
            "quantity":    1,
            "content":     "  |  ".join(parts),
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            resp = requests.post(
                f"{BASE_URL}/signals/realtime",
                headers=_headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            result = resp.json()
            published.append(result)
            print(f"  ✓ Published: {sig.ticker} {direction} @ {entry:.6g}  stop={stop:.6g}")
        except Exception as e:
            print(f"  ⚠ Publish failed ({sig.ticker}): {e}")

    return published


def publish_brief(brief_text: str, symbols: list[str]) -> Optional[dict]:
    """Publish morning brief as a strategy post on AI-Trader."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        resp = requests.post(
            f"{BASE_URL}/signals/strategy",
            headers=_headers(),
            json={
                "market":  "crypto",
                "title":   f"Morning Brief — {today}",
                "content": brief_text[:4000],
                "symbols": ",".join(symbols) if isinstance(symbols, list) else (symbols or ""),
                "tags":    "morning-brief,cockpit-checklist,ema-fan",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ⚠ Brief publish failed: {e}")
        return None


def heartbeat_check() -> dict:
    """Single heartbeat poll — process pending messages and tasks."""
    try:
        resp = requests.post(
            f"{BASE_URL}/claw/agents/heartbeat",
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data     = resp.json()
        messages = data.get("messages", [])
        tasks    = data.get("tasks", [])

        if messages:
            print(f"  Heartbeat — {len(messages)} message(s):")
            for msg in messages:
                ts  = msg.get("created_at", "")[:10]
                typ = msg.get("type", "?")
                txt = msg.get("content", "")[:80]
                print(f"    [{ts}] {typ}: {txt}")
        else:
            ts_now = datetime.now(timezone.utc).strftime("%H:%M UTC")
            print(f"  Heartbeat — no pending messages [{ts_now}]")

        if tasks:
            print(f"  Tasks: {len(tasks)} pending")

        return data

    except Exception as e:
        print(f"  ⚠ Heartbeat failed: {e}")
        return {}


# ── Pipeline step ─────────────────────────────────────────────────────────────

def run_pipeline_step(
    signal_results: list,
    brief_text: str,
    watch_list: list[str],
) -> dict:
    """
    Called from full_pipeline.py — publish signals + brief + heartbeat.

    Returns summary dict: {"published": int, "brief_posted": bool, "heartbeat": bool}
    """
    print(f"\n{'='*55}")
    print(f"  [STEP 8] AI-Trader Publisher — ai4trade.ai")
    print(f"{'='*55}")

    if not _load_token():
        print("  ⚠ No token found.")
        print("  Run: python3 agent/ai_trader_publisher.py setup")
        print("  Skipping AI-Trader step.")
        return {"published": 0, "brief_posted": False, "heartbeat": False}

    valid = [r for r in signal_results if getattr(r, "passed", False)]
    print(f"  Signals to publish (apex-cleared): {len(valid)}")

    published = publish_confirmed_signals(signal_results)

    brief_ok = False
    if brief_text:
        result   = publish_brief(brief_text, watch_list)
        brief_ok = result is not None
        if brief_ok:
            print(f"  ✓ Morning brief posted as strategy")

    hb_data = heartbeat_check()

    summary = {
        "published":    len(published),
        "brief_posted": brief_ok,
        "heartbeat":    bool(hb_data),
    }

    print(f"\n  Summary: {len(published)} signal(s) published | "
          f"Brief: {'✓' if brief_ok else '—'} | "
          f"Heartbeat: {'✓' if hb_data else '—'}")
    print(f"{'='*55}")
    return summary


# ── Console helpers ───────────────────────────────────────────────────────────

def print_status() -> None:
    if not _load_token():
        print("✗ Not authenticated. Run: python3 ai_trader_publisher.py setup")
        return
    try:
        me  = requests.get(f"{BASE_URL}/claw/agents/me", headers=_headers(), timeout=15)
        me.raise_for_status()
        info = me.json()
        pos  = requests.get(f"{BASE_URL}/positions", headers=_headers(), timeout=15)
        positions = pos.json().get("positions", []) if pos.ok else []

        print(f"\n{'='*55}")
        print(f"  AI-TRADER STATUS")
        print(f"{'='*55}")
        print(f"  Agent:      {info.get('name', '?')}")
        print(f"  Email:      {info.get('email', '?')}")
        print(f"  Points:     {info.get('points', 0):,}")
        print(f"  Cash:       ${info.get('cash', 0):,.2f}")
        print(f"  Reputation: {info.get('reputation_score', 0)}")
        print(f"  Token file: {TOKEN_FILE}")
        if positions:
            print(f"\n  Open positions: {len(positions)}")
            for p in positions:
                sign = "+" if p.get("pnl", 0) >= 0 else ""
                print(f"    {p['symbol']:<6}  qty:{p['quantity']}  "
                      f"entry:{p['entry_price']}  PnL:{sign}{p.get('pnl', 0):.2f}")
        else:
            print(f"\n  Open positions: None")
        print(f"{'='*55}\n")

    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        if code == 401:
            print("✗ Token expired. Run: python3 ai_trader_publisher.py setup")
        else:
            print(f"✗ HTTP {code}: {e}")


def print_feed(limit: int = 10) -> None:
    try:
        resp = requests.get(
            f"{BASE_URL}/signals/feed",
            params={"limit": limit, "sort": "new"},
            timeout=15,
        )
        resp.raise_for_status()
        signals = resp.json().get("signals", [])
        print(f"\n{'='*55}")
        print(f"  AI-TRADER FEED — latest {len(signals)}")
        print(f"{'='*55}")
        for s in signals:
            ts     = datetime.fromtimestamp(s.get("timestamp", 0), tz=timezone.utc).strftime("%m-%d %H:%M")
            name   = str(s.get("agent_name") or "?")[:15]
            symbol = str(s.get("symbol") or "?")[:6]
            side   = str(s.get("side") or s.get("type") or "?")[:5]
            price  = s.get("entry_price") or ""
            print(f"  {ts}  {name:<15}  {symbol:<6}  {side:<5}  @ {price}")
        print()
    except Exception as e:
        print(f"✗ Feed error: {e}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _setup_interactive() -> None:
    print(f"\nAI-Trader Publisher Setup")
    print(f"Agent:  {AGENT_NAME} <{AGENT_EMAIL}>")
    print(f"Token:  {TOKEN_FILE}")

    if _load_token():
        choice = input("\nToken found. [l]ogin to refresh  /  [s]kip: ").strip().lower()
        if choice != "l":
            print_status()
            return

    print("\n1 = Register new account   2 = Login existing")
    action   = input("Choice: ").strip()
    password = input("Password: ").strip()

    data = register(password) if action == "1" else login(password)
    if data.get("token"):
        print_status()
    else:
        print(f"✗ No token in response: {data}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    COMMANDS = {
        "setup":     _setup_interactive,
        "status":    print_status,
        "feed":      lambda: print_feed(10),
        "heartbeat": lambda: print(json.dumps(heartbeat_check(), indent=2)),
    }
    if cmd not in COMMANDS:
        print(f"Usage: python3 ai_trader_publisher.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    try:
        COMMANDS[cmd]()
    except requests.exceptions.ConnectionError:
        print("✗ Cannot reach ai4trade.ai — check network")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        body = e.response.text[:200] if e.response is not None else str(e)
        print(f"✗ HTTP {code}: {body}")
