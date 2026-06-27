"""
rithmic_executor.py — Mac-native Rithmic futures executor for Apex PA-50K.

Replaces MT5 entirely. Connects via Rithmic Protocol Buffer API.
Receives apex-cleared SignalResult objects from full_pipeline / apex_guard.

Libraries (reference repos — add as submodules, then install):
  - references/async-rithmic  → pip install async-rithmic        (primary)
    GitHub: https://github.com/rundef/async_rithmic
  - references/pyrithmic      → pip install git+https://github.com/jacksonwoody/pyrithmic.git
    GitHub: https://github.com/jacksonwoody/pyrithmic             (fallback, sync API)

Config: ~/.tradingvault/rithmic.json  (credentials — never commit)
State:  ~/.tradingvault/apex_state.json (trailing drawdown — apex_guard.py)

HARD RULES (enforced before every order):
  - check_apex_guard() must PASS
  - Never exceed daily loss limit $1,000
  - Never breach trailing drawdown floor $47,500 (PA-50K)
  - No signal without ATR(7) stop (rules.md §4)

Usage:
    python3 rithmic_executor.py --dry-run              # print orders, no submit
    python3 rithmic_executor.py --live                 # submit to Rithmic
    python3 rithmic_executor.py --sync-balance       # pull PNL → apex_state.json
    python3 rithmic_executor.py --status               # account + apex state
    python3 rithmic_executor.py --json '{...}'         # single signal JSON
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

VAULT_ROOT    = Path(__file__).parent.parent
DECISIONS_LOG = VAULT_ROOT / "logs" / "decisions-log.md"
CONFIG_FILE   = Path.home() / ".tradingvault" / "rithmic.json"
STATE_FILE    = Path.home() / ".tradingvault" / "apex_state.json"

# PA-50K hard limits (user-specified; enforced in addition to apex_guard)
HARD_DAILY_LOSS_LIMIT   = 1_000.0
HARD_TRAILING_FLOOR     = 47_500.0   # $50K - $2,500 trailing drawdown
DEFAULT_ACCOUNT_SIZE    = 50_000.0

# Vault crypto ticker → CME micro/root symbol for Apex futures routing
# tick_size / tick_value used to convert ATR(7) price distance → Rithmic stop_ticks
FUTURES_MAP: dict[str, dict] = {
    "BTC":  {"root": "MBT", "exchange": "CME", "tick_size": 5.0,   "tick_value": 0.50},
    "ETH":  {"root": "MET", "exchange": "CME", "tick_size": 0.25,  "tick_value": 0.25},
    "SOL":  {"root": "MNQ", "exchange": "CME", "tick_size": 0.25,  "tick_value": 0.50},
    "XRP":  {"root": "MES", "exchange": "CME", "tick_size": 0.25,  "tick_value": 1.25},
    "LINK": {"root": "MES", "exchange": "CME", "tick_size": 0.25,  "tick_value": 1.25},
    "PEPE": {"root": "MES", "exchange": "CME", "tick_size": 0.25,  "tick_value": 1.25},
}


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class RithmicConfig:
    user:         str
    password:     str
    system_name:  str
    app_name:     str  = "TradingVault"
    app_version:  str  = "1.0"
    url:          str  = ""
    gateway:      str  = ""          # e.g. "TEST" or Apex gateway URL
    account_id:   str  = ""
    default_qty:  int  = 1
    paper_mode:   bool = True        # default paper — live requires --live flag


def load_config() -> RithmicConfig:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Rithmic config not found: {CONFIG_FILE}\n"
            "Create it from the template below:\n"
            + _config_template()
        )
    data = json.loads(CONFIG_FILE.read_text())
    return RithmicConfig(
        user        = data["user"],
        password    = data["password"],
        system_name = data.get("system_name", "Rithmic Paper Trading"),
        app_name    = data.get("app_name", "TradingVault"),
        app_version = data.get("app_version", "1.0"),
        url         = data.get("url", ""),
        gateway     = data.get("gateway", ""),
        account_id  = data.get("account_id", ""),
        default_qty = int(data.get("default_qty", 1)),
        paper_mode  = bool(data.get("paper_mode", True)),
    )


def _config_template() -> str:
    return json.dumps({
        "user":         "YOUR_RITHMIC_USER",
        "password":     "YOUR_RITHMIC_PASSWORD",
        "system_name":  "Rithmic Paper Trading",
        "app_name":     "TradingVault",
        "app_version":  "1.0",
        "url":          "rituz00100.rithmic.com:443",
        "gateway":      "",
        "account_id":   "APEX-XXXXX",
        "default_qty":  1,
        "paper_mode":   True,
    }, indent=2)


# ── Order spec ────────────────────────────────────────────────────────────────

@dataclass
class RithmicOrderSpec:
    ticker:           str
    direction:        str           # LONG | SHORT
    entry_price:      float
    stop_loss:        float
    target_1r:        float
    qty:              int
    root_symbol:      str
    exchange:         str
    security_code:    str = ""
    stop_ticks:       int = 0
    target_ticks:     int = 0
    atr_7:            float = 0.0
    order_id:         str = field(default_factory=lambda: _new_order_id())

    def to_dict(self) -> dict:
        return {
            "order_id":      self.order_id,
            "ticker":        self.ticker,
            "direction":     self.direction,
            "entry_price":   self.entry_price,
            "stop_loss":     self.stop_loss,
            "target_1r":     self.target_1r,
            "qty":           self.qty,
            "root_symbol":   self.root_symbol,
            "exchange":      self.exchange,
            "security_code": self.security_code,
            "stop_ticks":    self.stop_ticks,
            "target_ticks":  self.target_ticks,
            "atr_7":         self.atr_7,
        }


def _new_order_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"TV_{ts}_{uuid.uuid4().hex[:8]}"


def _price_distance_to_ticks(distance: float, tick_size: float) -> int:
    if tick_size <= 0:
        return 0
    return max(1, int(round(abs(distance) / tick_size)))


# ── Validation + Apex guard ───────────────────────────────────────────────────

def validate_signal(sig: Any) -> list[str]:
    """Return blocking errors. Empty list = OK to proceed."""
    errors: list[str] = []
    if not getattr(sig, "passed", False):
        errors.append("Signal did not pass Cockpit Checklist")
    stop = float(getattr(sig, "stop_loss", 0.0) or 0.0)
    if stop <= 0:
        errors.append("No ATR(7) stop — rules.md §4")
    entry = float(getattr(sig, "entry_price", 0.0) or 0.0)
    if entry <= 0:
        errors.append("No entry price")
    ticker = getattr(sig, "ticker", "")
    if ticker not in FUTURES_MAP:
        errors.append(f"No futures mapping for ticker {ticker}")
    direction = getattr(getattr(sig, "signal_type", None), "value", None)
    if direction not in ("LONG", "SHORT"):
        errors.append(f"Invalid direction: {direction}")
    return errors


def enforce_apex_limits(atr_7: float = 0.0) -> tuple[bool, str]:
    """
    Run apex_guard + hard PA-50K limits before every order.
    Returns (passed, reason).
    """
    from apex_guard import check_apex_guard, _load_state

    state = _load_state()
    balance   = float(state.get("current_balance", DEFAULT_ACCOUNT_SIZE))
    today_pnl = float(state.get("today_pnl", 0.0))
    peak      = float(state.get("peak_eod_balance", DEFAULT_ACCOUNT_SIZE))
    trailing  = float(state.get("trailing_drawdown", 2_500))
    floor     = max(HARD_TRAILING_FLOOR, peak - trailing)

    if balance <= floor:
        return False, (
            f"HARD FLOOR — balance ${balance:,.2f} <= floor ${floor:,.2f}"
        )

    if today_pnl <= -HARD_DAILY_LOSS_LIMIT:
        return False, (
            f"DAILY LIMIT — today P&L ${today_pnl:+,.2f} hit -${HARD_DAILY_LOSS_LIMIT:,.0f} cap"
        )

    guard = check_apex_guard(atr_7=atr_7)
    if not guard.passed:
        return False, guard.reason

    return True, guard.reason


def build_order_spec(sig: Any, qty: int = 1) -> RithmicOrderSpec:
    """Convert apex-cleared SignalResult → Rithmic bracket order spec."""
    mapping   = FUTURES_MAP[sig.ticker]
    tick_size = float(mapping["tick_size"])
    direction = sig.signal_type.value
    entry     = float(sig.entry_price)
    stop      = float(sig.stop_loss)
    target    = float(sig.target_1r)

    stop_dist   = abs(entry - stop)
    target_dist = abs(target - entry)

    return RithmicOrderSpec(
        ticker        = sig.ticker,
        direction     = direction,
        entry_price   = entry,
        stop_loss     = stop,
        target_1r     = target,
        qty           = qty,
        root_symbol   = mapping["root"],
        exchange      = mapping["exchange"],
        stop_ticks    = _price_distance_to_ticks(stop_dist, tick_size),
        target_ticks  = _price_distance_to_ticks(target_dist, tick_size),
        atr_7         = float(getattr(sig, "atr_value", 0.0) or 0.0),
    )


# ── Logging ───────────────────────────────────────────────────────────────────

def log_execution(
    spec: RithmicOrderSpec,
    status: str,
    detail: str = "",
    fill_price: Optional[float] = None,
) -> None:
    """Append execution row to logs/decisions-log.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    side = "BUY" if spec.direction == "LONG" else "SELL"
    fill_str = f" fill={fill_price}" if fill_price is not None else ""
    row = (
        f"\n| {now} | RITHMIC {status} | {spec.ticker} | "
        f"{spec.root_symbol} {side} | qty={spec.qty} | "
        f"entry={spec.entry_price} | stop={spec.stop_loss} | "
        f"target={spec.target_1r} | stop_ticks={spec.stop_ticks} | "
        f"{detail}{fill_str} |\n"
    )
    try:
        with open(DECISIONS_LOG, "a") as f:
            f.write(row)
    except OSError:
        pass


def log_block(ticker: str, reason: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    row = f"\n| {now} | RITHMIC BLOCK | {ticker} | — | — | — | — | {reason} |\n"
    try:
        with open(DECISIONS_LOG, "a") as f:
            f.write(row)
    except OSError:
        pass


# ── Balance sync ──────────────────────────────────────────────────────────────

def _extract_balance(pnl_data: Any) -> Optional[float]:
    """Parse AccountPnLPositionUpdate from list_account_summary() (async_rithmic)."""
    if pnl_data is None:
        return None
    if isinstance(pnl_data, dict):
        for key in ("account_balance", "margin_balance", "mtm_account", "cash_on_hand"):
            if key in pnl_data and pnl_data[key] not in (None, ""):
                return float(pnl_data[key])
    for attr in ("account_balance", "margin_balance", "mtm_account", "cash_on_hand"):
        val = getattr(pnl_data, attr, None)
        if val not in (None, ""):
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def update_apex_balance(new_balance: float, pnl_delta: Optional[float] = None) -> None:
    """Write live balance to apex_state.json after fill or PNL sync."""
    from apex_guard import _load_state, _save_state

    state = _load_state()
    old_balance = float(state.get("current_balance", DEFAULT_ACCOUNT_SIZE))
    state["current_balance"] = new_balance

    if pnl_delta is not None:
        state["today_pnl"] = float(state.get("today_pnl", 0.0)) + pnl_delta
    elif new_balance != old_balance:
        state["today_pnl"] = float(state.get("today_pnl", 0.0)) + (new_balance - old_balance)

    _save_state(state)
    print(f"  ✓ apex_state.json updated — balance ${new_balance:,.2f}  "
          f"today_pnl ${state['today_pnl']:+,.2f}")


async def sync_balance_from_client(
    client,
    config: RithmicConfig,
) -> Optional[float]:
    """Pull account PNL snapshot using an existing connected client."""
    try:
        summaries = await client.list_account_summary(
            account_id=config.account_id or None
        )
        balance = None
        if summaries:
            balance = _extract_balance(
                summaries[0] if isinstance(summaries, list) else summaries
            )
        if balance is not None:
            update_apex_balance(balance)
            return balance
        return None
    except Exception as exc:
        print(f"  ⚠ Balance sync failed: {exc}")
        return None


async def sync_balance_from_rithmic(config: RithmicConfig) -> Optional[float]:
    """Pull account PNL snapshot from Rithmic → apex_state.json."""
    client = _build_client(config)
    await client.connect()
    try:
        return await sync_balance_from_client(client, config)
    finally:
        await client.disconnect()


# ── Rithmic client ────────────────────────────────────────────────────────────

def _build_client(config: RithmicConfig):
    """Instantiate async_rithmic RithmicClient from config.

    API (references/async-rithmic/async_rithmic/client.py):
      RithmicClient(user, password, system_name, app_name, app_version, url, ...)
      client.connect(**kwargs)
      client.submit_order(order_id, symbol, exchange, qty=..., ...)
      client.list_account_summary(account_id=...)
    """
    try:
        from async_rithmic import RithmicClient
    except ImportError as exc:
        raise ImportError(
            "async_rithmic not installed. Run: pip install async_rithmic"
        ) from exc

    url = config.url.strip()
    if not url and config.gateway.strip():
        gw = config.gateway.strip()
        url = gw if "://" in gw else f"wss://{gw}"
    if not url:
        raise ValueError(
            "Rithmic config requires 'url' (wss://host:port). "
            f"Set url in {CONFIG_FILE}"
        )

    return RithmicClient(
        user         = config.user,
        password     = config.password,
        system_name  = config.system_name,
        app_name     = config.app_name,
        app_version  = config.app_version,
        url          = url,
    )


def _submit_via_pyrithmic(spec: RithmicOrderSpec) -> bool:
    """
    Fallback submit using pyrithmic (sync, simpler API).
    Called when async_rithmic is unavailable or connection fails.

    Requires: pip install git+https://github.com/jacksonwoody/pyrithmic.git
              RITHMIC_CREDENTIALS_PATH env var pointing to folder with .ini files
    """
    try:
        from rithmic import RithmicOrderApi, RithmicEnvironment
    except ImportError:
        return False

    creds_dir = Path(os.environ.get("RITHMIC_CREDENTIALS_PATH", Path.home() / ".rithmic"))
    if not creds_dir.exists():
        print(f"  ⚠ pyrithmic: RITHMIC_CREDENTIALS_PATH not set or missing ({creds_dir})")
        return False

    try:
        env = RithmicEnvironment.RITHMIC_PAPER_TRADING  # always paper until live confirmed
        api = RithmicOrderApi(env=env)
        is_buy = spec.direction == "LONG"
        order = api.submit_bracket_order(
            order_id          = spec.order_id,
            security_code     = spec.security_code or spec.root_symbol,
            exchange_code     = spec.exchange,
            quantity          = spec.qty,
            is_buy            = is_buy,
            limit_price       = spec.entry_price,
            take_profit_ticks = spec.target_ticks,
            stop_loss_ticks   = spec.stop_ticks,
        )
        print(f"  ✓ pyrithmic: bracket order submitted — {spec.order_id}")
        print(f"    in_market: {getattr(order, 'in_market', '?')}")
        return True
    except Exception as e:
        print(f"  ⚠ pyrithmic submit failed: {e}")
        return False


def format_order_console(spec: RithmicOrderSpec, guard_reason: str = "") -> str:
    side = "BUY" if spec.direction == "LONG" else "SELL"
    lines = [
        "",
        "═" * 60,
        "  RITHMIC EXECUTOR — BRACKET ORDER",
        "═" * 60,
        f"  Order ID:       {spec.order_id}",
        f"  Vault ticker:   {spec.ticker}",
        f"  Contract:       {spec.root_symbol} @ {spec.exchange}",
        f"  Security code:  {spec.security_code or '(resolve at submit)'}",
        f"  Side:           {side}  qty={spec.qty}",
        f"  Entry (ref):    {spec.entry_price}",
        f"  Stop (ATR7):    {spec.stop_loss}  →  {spec.stop_ticks} ticks",
        f"  Target 1R:      {spec.target_1r}  →  {spec.target_ticks} ticks",
        f"  ATR(7):         {spec.atr_7}",
    ]
    if guard_reason:
        lines.append(f"  Apex guard:     {guard_reason}")
    lines += [
        "",
        "  ⚠  Bracket attaches stop_ticks + target_ticks to entry (async_rithmic)",
        "═" * 60,
    ]
    return "\n".join(lines)


# ── Order submission ──────────────────────────────────────────────────────────

async def _resolve_security_code(client, spec: RithmicOrderSpec) -> str:
    if spec.security_code:
        return spec.security_code
    code = await client.get_front_month_contract(spec.root_symbol, spec.exchange)
    spec.security_code = code
    return code


async def _submit_bracket(client, config: RithmicConfig, spec: RithmicOrderSpec) -> dict:
    from async_rithmic import OrderType, TransactionType

    security_code = await _resolve_security_code(client, spec)
    txn = TransactionType.BUY if spec.direction == "LONG" else TransactionType.SELL

    await client.submit_order(
        order_id      = spec.order_id,
        symbol        = security_code,
        exchange      = spec.exchange,
        qty           = spec.qty,
        order_type    = OrderType.LIMIT,
        transaction_type = txn,
        price         = spec.entry_price,
        stop_ticks    = spec.stop_ticks,
        target_ticks  = spec.target_ticks,
        stop_market_on_reject = True,
        **({"account_id": config.account_id} if config.account_id else {}),
    )
    return {"order_id": spec.order_id, "security_code": security_code, "status": "submitted"}


async def execute_orders_async(
    apex_cleared: list,
    *,
    live: bool = False,
    qty: Optional[int] = None,
) -> list[dict]:
    """
    Execute apex-cleared signals on Rithmic.

    Args:
        apex_cleared: SignalResult list from apex_guard / full_pipeline
        live:         If False, dry-run only (print + log STAGED)
        qty:          Contract quantity override

    Returns list of result dicts per signal.
    """
    results: list[dict] = []

    if not apex_cleared:
        print("  No apex-cleared signals — Rithmic step skipped")
        return results

    config: Optional[RithmicConfig] = None
    client = None

    if live:
        config = load_config()
        if config.paper_mode:
            print("  Mode: PAPER (Rithmic paper trading)")
        else:
            print("  ⚠ Mode: LIVE — real Apex account")
        try:
            client = _build_client(config)
            await client.connect()
        except ImportError:
            print("  ⚠ async_rithmic not installed — falling back to pyrithmic for submission")
            client = None  # pyrithmic fallback used per-order below

        # Track pending specs by order_id for fill logging
        pending: dict[str, RithmicOrderSpec] = {}

        async def on_fill(notification: Any) -> None:
            try:
                from async_rithmic import ExchangeOrderNotificationType
                ntype = getattr(notification, "notify_type", None)
                if ntype != ExchangeOrderNotificationType.FILL:
                    return
                fill_price = float(getattr(notification, "fill_price", 0) or 0)
                order_id   = str(getattr(notification, "user_tag", "") or "")
                qty        = int(getattr(notification, "fill_size", 0) or 0)
                print(f"  ✓ FILL {order_id} @ {fill_price}  qty={qty}")

                spec = pending.get(order_id)
                if spec:
                    log_execution(
                        spec, "FILLED",
                        detail=f"order_id={order_id} qty={qty}",
                        fill_price=fill_price,
                    )

                # Update apex_state.json after every fill
                if client is not None:
                    bal = await sync_balance_from_client(client, config)
                    if bal is None:
                        print("  ⚠ Fill recorded — balance sync returned no data")
            except Exception as exc:
                print(f"  ⚠ Fill handler error: {exc}")

        if client is not None:
            try:
                client.on_exchange_order_notification += on_fill
            except Exception:
                pass

    try:
        default_qty = qty or (config.default_qty if config else 1)

        for sig in apex_cleared:
            errors = validate_signal(sig)
            if errors:
                reason = "; ".join(errors)
                print(f"  ✗ BLOCKED {sig.ticker}: {reason}")
                log_block(sig.ticker, reason)
                results.append({"ticker": sig.ticker, "status": "blocked", "reason": reason})
                continue

            ok, guard_reason = enforce_apex_limits(atr_7=float(sig.atr_value or 0.0))
            if not ok:
                print(f"  ✗ APEX BLOCK {sig.ticker}: {guard_reason}")
                log_block(sig.ticker, guard_reason)
                results.append({"ticker": sig.ticker, "status": "apex_blocked", "reason": guard_reason})
                continue

            spec = build_order_spec(sig, qty=default_qty)
            print(format_order_console(spec, guard_reason))

            if not live:
                log_execution(spec, "STAGED", detail="dry-run — not submitted")
                results.append({"ticker": sig.ticker, "status": "staged", "order": spec.to_dict()})
                continue

            # Re-check apex guard immediately before submit
            ok, guard_reason = enforce_apex_limits(atr_7=spec.atr_7)
            if not ok:
                log_block(sig.ticker, f"Pre-submit re-check: {guard_reason}")
                results.append({"ticker": sig.ticker, "status": "apex_blocked", "reason": guard_reason})
                continue

            assert config is not None
            if client is not None:
                pending[spec.order_id] = spec
                submit_result = await _submit_bracket(client, config, spec)
            else:
                # async_rithmic unavailable — try pyrithmic sync fallback
                ok = _submit_via_pyrithmic(spec)
                submit_result = {
                    "order_id":      spec.order_id,
                    "security_code": spec.security_code,
                    "status":        "submitted" if ok else "pyrithmic_failed",
                }
                if not ok:
                    log_block(sig.ticker, "pyrithmic fallback also failed — no library available")
                    results.append({"ticker": sig.ticker, "status": "blocked", "reason": "no rithmic library"})
                    continue
            log_execution(spec, "SUBMITTED", detail=f"order_id={spec.order_id}")
            results.append({"ticker": sig.ticker, "status": "submitted", **submit_result})

            # Initial balance sync after submit
            await asyncio.sleep(1.5)
            if client is not None:
                await sync_balance_from_client(client, config)

    finally:
        if client is not None:
            await client.disconnect()

    return results


def execute_apex_cleared(
    apex_cleared: list,
    *,
    live: bool = False,
    qty: Optional[int] = None,
) -> list[dict]:
    """Sync entry point for full_pipeline.py."""
    return asyncio.run(execute_orders_async(apex_cleared, live=live, qty=qty))


# ── Status ────────────────────────────────────────────────────────────────────

def print_status() -> None:
    from apex_guard import _load_state, check_apex_guard

    print("\n" + "═" * 55)
    print("  RITHMIC EXECUTOR — STATUS")
    print("═" * 55)

    if CONFIG_FILE.exists():
        cfg = load_config()
        print(f"  Config:       {CONFIG_FILE}")
        print(f"  User:         {cfg.user}")
        print(f"  System:       {cfg.system_name}")
        print(f"  Account:      {cfg.account_id or '(default)'}")
    else:
        print(f"  Config:       ✗ missing — {CONFIG_FILE}")

    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
        balance = float(state.get("current_balance", 0))
        peak    = float(state.get("peak_eod_balance", DEFAULT_ACCOUNT_SIZE))
        floor   = max(HARD_TRAILING_FLOOR, peak - float(state.get("trailing_drawdown", 2500)))
        pnl     = float(state.get("today_pnl", 0))
        print(f"\n  Apex balance: ${balance:,.2f}")
        print(f"  Trailing floor: ${floor:,.2f}  (hard min ${HARD_TRAILING_FLOOR:,.2f})")
        print(f"  Today P&L:    ${pnl:+,.2f}  (limit -${HARD_DAILY_LOSS_LIMIT:,.0f})")
        print(f"  Distance:     ${balance - floor:,.2f}")

    guard = check_apex_guard(atr_7=0.0)
    print(f"\n  Apex guard:   {'PASS' if guard.passed else 'BLOCK'}")
    print(f"  {guard.reason}")
    print("═" * 55 + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _signal_from_dict(data: dict) -> Any:
    """Minimal SignalResult-like object from JSON."""
    from signal_checker import SignalResult, SignalType

    st = data.get("signal_type", data.get("direction", "LONG"))
    if isinstance(st, str):
        signal_type = SignalType[st.upper()] if st.upper() in SignalType.__members__ else SignalType.LONG
    else:
        signal_type = SignalType.LONG

    return SignalResult(
        ticker       = data["ticker"],
        timeframe    = data.get("timeframe", "1w"),
        signal_type  = signal_type,
        passed       = bool(data.get("passed", True)),
        entry_price  = float(data["entry_price"]),
        stop_loss    = float(data["stop_loss"]),
        target_1r    = float(data.get("target_1r", 0)),
        atr_value    = float(data.get("atr_value", data.get("atr_7", 0))),
        ema_trend    = data.get("ema_trend", ""),
        body_rule    = bool(data.get("body_rule", True)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rithmic futures executor — Apex PA-50K")
    parser.add_argument("--live", action="store_true",
                        help="Submit to Rithmic LIVE account (default: paper/dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print + log orders without submitting (default when --live omitted)")
    parser.add_argument("--sync-balance", action="store_true",
                        help="Pull PNL from Rithmic → apex_state.json")
    parser.add_argument("--status", action="store_true",
                        help="Show config + apex state")
    parser.add_argument("--qty", type=int, default=None, help="Contract quantity")
    parser.add_argument("--json", dest="json_signal", help="Single signal JSON")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    if args.sync_balance:
        config = load_config()
        balance = asyncio.run(sync_balance_from_rithmic(config))
        if balance is not None:
            print(f"  ✓ Synced balance: ${balance:,.2f}")
        return

    live = args.live and not args.dry_run

    if args.json_signal:
        data = json.loads(args.json_signal)
        sig  = _signal_from_dict(data)
        apex_cleared = [sig] if sig.passed else []
    else:
        # Demo: LINK Gartley D-point from morning brief
        print("\n[rithmic_executor] Demo mode — LINK SHORT example\n")
        from signal_checker import SignalResult, SignalType
        sig = SignalResult(
            ticker      = "LINK",
            timeframe   = "1w",
            signal_type = SignalType.SHORT,
            passed      = True,
            entry_price = 7.35823,
            stop_loss   = 7.35823 + 0.9743,
            target_1r   = 7.35823 - 0.9743,
            atr_value   = 0.9743,
            ema_trend   = "FANNING-BEAR",
            body_rule   = False,
        )
        apex_cleared = [sig]

    if not live:
        print("  Mode: DRY-RUN (pass --live to submit to Rithmic)\n")

    results = execute_apex_cleared(apex_cleared, live=live, qty=args.qty)
    submitted = sum(1 for r in results if r.get("status") == "submitted")
    staged    = sum(1 for r in results if r.get("status") == "staged")
    blocked   = sum(1 for r in results if "blocked" in r.get("status", ""))
    print(f"\n  Done: {submitted} submitted | {staged} staged | {blocked} blocked")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
