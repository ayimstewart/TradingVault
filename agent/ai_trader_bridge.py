"""
ai_trader_bridge.py — AI-Trader (ai4trade.ai) integration layer.

Publishes checklist-approved signals to the AI-Trader platform for
recording, copy trading, and community participation.

HARD RULE: Only signals that have PASSED the full Cockpit Checklist
           (rules.md §1–4) may be published. This module enforces
           that gate — it will reject any signal that has not passed.

Usage:
    python3 ai_trader_bridge.py setup      # register/login and save token
    python3 ai_trader_bridge.py status     # check auth and account info
    python3 ai_trader_bridge.py heartbeat  # poll one heartbeat
    python3 ai_trader_bridge.py feed       # show recent signal feed

Config file: ~/.tradingvault/ai_trader.json
  (token stored here — never committed to git)

Integration with run_session.py:
    from ai_trader_bridge import publish_signal, publish_morning_brief
    publish_signal(signal_result)   # after checklist passes
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL    = "https://ai4trade.ai/api"
CONFIG_DIR  = Path.home() / ".tradingvault"
CONFIG_FILE = CONFIG_DIR / "ai_trader.json"
VAULT_ROOT  = Path(__file__).parent.parent

AGENT_NAME  = "TradingVault"
AGENT_EMAIL = os.environ.get("AI_TRADER_EMAIL", "stewartankrah05@gmail.com")


def _load_config() -> dict:
    """Load stored token and agent_id."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_config(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
    CONFIG_FILE.chmod(0o600)  # owner-only read


def _get_token() -> Optional[str]:
    return _load_config().get("token")


def _headers() -> dict:
    token = _get_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def register(password: str) -> dict:
    """Create a new agent account. Call once, then use login() thereafter."""
    resp = requests.post(f"{BASE_URL}/claw/agents/selfRegister", json={
        "name":     AGENT_NAME,
        "email":    AGENT_EMAIL,
        "password": password,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("success") or data.get("token"):
        cfg = _load_config()
        cfg.update({
            "token":    data["token"],
            "agent_id": data.get("agent_id"),
            "email":    AGENT_EMAIL,
        })
        _save_config(cfg)
        print(f"✓ Registered: {AGENT_NAME} (agent_id: {data.get('agent_id')})")
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
        cfg = _load_config()
        cfg["token"] = data["token"]
        _save_config(cfg)
        print(f"✓ Logged in — token refreshed")
    return data


def get_me() -> dict:
    """Return current agent profile (name, points, cash, reputation)."""
    resp = requests.get(f"{BASE_URL}/claw/agents/me", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Signal publishing ─────────────────────────────────────────────────────────

def publish_signal(signal, note: str = "") -> dict:
    """
    Publish a checklist-approved signal as a realtime trade to AI-Trader.

    Args:
        signal: A SignalResult from signal_checker that has passed (signal.passed == True)
        note:   Optional context note appended to the trade content

    Returns the AI-Trader API response dict.
    """
    if not getattr(signal, "passed", False):
        raise ValueError(
            f"publish_signal called on a BLOCKED signal for {signal.ticker}. "
            "Only call after Cockpit Checklist passes (rules.md §1-4)."
        )

    stop = float(getattr(signal, "stop_loss", 0.0) or 0.0)
    if stop <= 0:
        raise ValueError(
            f"publish_signal blocked for {signal.ticker}: No ATR(7) stop (rules.md §4)."
        )

    entry = float(getattr(signal, "entry_price", 0.0) or 0.0)
    if entry <= 0:
        raise ValueError(f"publish_signal blocked for {signal.ticker}: No entry price.")

    direction = signal.signal_type.value   # "LONG" or "SHORT"
    action    = "buy" if direction == "LONG" else "short"

    content_parts = [
        f"{signal.ticker} {direction}",
        f"Entry: {entry:.6g}",
        f"Stop (ATR7): {stop:.6g}",
        f"Target 1R: {signal.target_1r:.6g}",
        f"EMA: {signal.ema_trend}",
        f"TF: {signal.timeframe.upper()}",
    ]
    if note:
        content_parts.append(note)
    content = "  |  ".join(content_parts)

    payload = {
        "market":      "crypto",
        "action":      action,
        "symbol":      signal.ticker,
        "price":       entry,
        "quantity":    1,
        "content":     content,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }

    resp = requests.post(
        f"{BASE_URL}/signals/realtime",
        headers=_headers(),
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def publish_morning_brief(brief_text: str, symbols: list[str]) -> dict:
    """
    Publish the morning brief as a strategy post on AI-Trader.
    Called from run_session.py Step 5.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp  = requests.post(
        f"{BASE_URL}/signals/strategy",
        headers=_headers(),
        json={
            "market":  "crypto",
            "title":   f"Morning Brief — {today}",
            "content": brief_text,
            "symbols": ",".join(symbols) if isinstance(symbols, list) else (symbols or ""),
            "tags":    "morning-brief,cockpit-checklist,ema-fan",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def publish_session_summary(summary: str, valid_count: int) -> dict:
    """Post a session-close discussion summarising today's findings."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    resp  = requests.post(
        f"{BASE_URL}/signals/discussion",
        headers=_headers(),
        json={
            "market":  "crypto",
            "title":   f"Session Close — {today} ({valid_count} valid signals)",
            "content": summary,
            "tags":    "session-close,cockpit-checklist",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ── Feed & positions ──────────────────────────────────────────────────────────

def get_feed(limit: int = 10, symbol: Optional[str] = None) -> list[dict]:
    """Fetch the community signal feed."""
    params: dict = {"limit": limit, "sort": "new"}
    if symbol:
        params["symbol"] = symbol
    resp = requests.get(f"{BASE_URL}/signals/feed", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("signals", [])


def get_positions() -> dict:
    """Return current positions and cash balance."""
    resp = requests.get(f"{BASE_URL}/positions", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def poll_heartbeat() -> dict:
    """Poll the platform heartbeat once. Returns pending messages and tasks."""
    resp = requests.post(
        f"{BASE_URL}/claw/agents/heartbeat",
        headers=_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def run_heartbeat_loop(interval_override: Optional[int] = None) -> None:
    """
    Continuous heartbeat loop — processes notifications as they arrive.
    Ctrl+C to stop.
    """
    print(f"\n[Heartbeat] Starting loop for {AGENT_NAME}. Press Ctrl+C to stop.\n")
    while True:
        try:
            data     = poll_heartbeat()
            messages = data.get("messages", [])
            tasks    = data.get("tasks", [])
            interval = interval_override or data.get("recommended_poll_interval_seconds", 30)

            if messages:
                for msg in messages:
                    ts  = msg.get("created_at", "")[:10]
                    typ = msg.get("type", "?")
                    txt = msg.get("content", "")
                    print(f"  [{ts}] {typ}: {txt}")
            else:
                print(f"  [{datetime.now(timezone.utc).strftime('%H:%M')}] No new messages")

            if tasks:
                for task in tasks:
                    print(f"  TASK: {task.get('type')} — {task.get('input_data')}")

            if data.get("has_more_messages"):
                continue  # drain the queue

            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n[Heartbeat] Stopped.")
            break
        except Exception as e:
            print(f"  [Heartbeat] Error: {e}  (retrying in 60s)")
            time.sleep(60)


# ── Console display ───────────────────────────────────────────────────────────

def print_status() -> None:
    token = _get_token()
    if not token:
        print("✗ Not authenticated. Run: python3 ai_trader_bridge.py setup")
        return

    try:
        me = get_me()
        print(f"\n{'='*55}")
        print(f"  AI-TRADER STATUS")
        print(f"{'='*55}")
        print(f"  Agent:      {me.get('name', '?')}")
        print(f"  Email:      {me.get('email', '?')}")
        print(f"  Points:     {me.get('points', 0):,}")
        print(f"  Cash:       ${me.get('cash', 0):,.2f}")
        print(f"  Reputation: {me.get('reputation_score', 0)}")
        print(f"{'='*55}\n")

        pos = get_positions()
        positions = pos.get("positions", [])
        if positions:
            print(f"  Open positions: {len(positions)}")
            for p in positions:
                pnl_sign = "+" if p.get("pnl", 0) >= 0 else ""
                print(f"    {p['symbol']:<6} qty:{p['quantity']}  "
                      f"entry:{p['entry_price']}  "
                      f"PnL:{pnl_sign}{p.get('pnl', 0):.2f}")
        else:
            print(f"  Open positions: None")

    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            print("✗ Token expired. Run: python3 ai_trader_bridge.py setup")
        else:
            print(f"✗ API error: {e}")


def print_feed(limit: int = 10) -> None:
    signals = get_feed(limit=limit)
    print(f"\n{'='*55}")
    print(f"  AI-TRADER FEED — latest {len(signals)} signals")
    print(f"{'='*55}")
    for s in signals:
        ts     = datetime.fromtimestamp(s.get("timestamp", 0), tz=timezone.utc).strftime("%m-%d %H:%M")
        name   = str(s.get("agent_name") or "?")[:15]
        symbol = str(s.get("symbol") or "?")[:6]
        side   = str(s.get("side") or s.get("type") or "?")[:5]
        price  = s.get("entry_price") or ""
        print(f"  {ts}  {name:<15}  {symbol:<6}  {side:<5}  @ {price}")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────────

def _setup_interactive() -> None:
    """Interactive setup flow — register or login."""
    print(f"\nAI-Trader Setup — {BASE_URL}")
    print(f"Agent name:  {AGENT_NAME}")
    print(f"Agent email: {AGENT_EMAIL}")

    if CONFIG_FILE.exists() and _get_token():
        print(f"\nConfig found at {CONFIG_FILE}")
        action = input("  [l]ogin to refresh token  /  [s]kip (keep existing): ").strip().lower()
        if action != "l":
            print_status()
            return

    print("\n1 = Register new account   2 = Login existing")
    choice = input("Choice: ").strip()
    password = input("Password: ").strip()

    if choice == "1":
        data = register(password)
    else:
        data = login(password)

    if data.get("token"):
        print("✓ Token saved. Run status to verify.")
        print_status()
    else:
        print(f"✗ No token returned: {data}")


COMMANDS = {
    "setup":     _setup_interactive,
    "status":    print_status,
    "feed":      lambda: print_feed(10),
    "heartbeat": lambda: print(json.dumps(poll_heartbeat(), indent=2)),
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd not in COMMANDS:
        print(f"Usage: python3 ai_trader_bridge.py [{' | '.join(COMMANDS)}]")
        sys.exit(1)
    try:
        COMMANDS[cmd]()
    except requests.exceptions.ConnectionError:
        print("✗ Cannot reach ai4trade.ai — check network connection")
    except requests.HTTPError as e:
        print(f"✗ HTTP {e.response.status_code}: {e.response.text[:200]}")
