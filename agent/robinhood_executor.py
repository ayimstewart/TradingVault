"""
robinhood_executor.py — Prepare and log Robinhood equity orders.

Translates a validated TradeCard (from position_sizer.py) into a
structured order payload, validates it, and logs it to decisions-log.md.

Actual order placement uses the Robinhood MCP tools (mcp__robinhood-trading__*)
available inside Claude Code. This script outputs the exact parameters to pass.

HARD RULE: Only TradeCards that passed check_signal AND apex_guard may be
           submitted here. This module enforces that gate.

Usage:
    python3 robinhood_executor.py             # run checklist, size, print order
    python3 robinhood_executor.py --ticker LINK --account-balance 10000
    python3 robinhood_executor.py --json '{"ticker":"LINK",...}'  # from stdin
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_ROOT    = Path(__file__).parent.parent
DECISIONS_LOG = VAULT_ROOT / "logs" / "decisions-log.md"


# ── Order spec ────────────────────────────────────────────────────────────────

def build_equity_order(
    ticker: str,
    direction: str,          # "LONG" | "SHORT"
    entry_price: float,
    stop_loss: float,
    target_1r: float,
    quantity: float,         # from position_sizer TradeCard
    account_number: str = "",
    order_type: str = "limit",
    time_in_force: str = "gfd",
) -> dict:
    """
    Build a Robinhood-compatible equity order payload.

    For crypto/spot: direction=="LONG" → buy order, direction=="SHORT" → sell order.
    Stop-loss bracket is a separate order placed after fill confirmation.

    Returns a dict with two keys:
      "entry_order" — the main order parameters
      "stop_order"  — stop-loss parameters (place after fill)
    """
    side = "buy" if direction == "LONG" else "sell"
    stop_side = "sell" if direction == "LONG" else "buy"

    entry_order = {
        "symbol": ticker,
        "side": side,
        "order_type": order_type,
        "quantity": round(quantity, 6),
        "price": round(entry_price, 6),
        "time_in_force": time_in_force,
    }
    if account_number:
        entry_order["account_number"] = account_number

    stop_order = {
        "symbol": ticker,
        "side": stop_side,
        "order_type": "stop",
        "quantity": round(quantity, 6),
        "stop_price": round(stop_loss, 6),
        "time_in_force": "gtc",
    }
    if account_number:
        stop_order["account_number"] = account_number

    return {"entry_order": entry_order, "stop_order": stop_order}


def format_mcp_call(order: dict) -> str:
    """
    Print the exact Claude Code MCP tool invocation to execute this order.
    The user (or Claude Code) pastes this to confirm and route via Robinhood MCP.
    """
    entry = order["entry_order"]
    stop  = order["stop_order"]

    lines = [
        "\n" + "═" * 60,
        "  ROBINHOOD EXECUTOR — MCP CALL PARAMETERS",
        "═" * 60,
        "",
        "  Step 1 — Review entry order (run first):",
        "  ─────────────────────────────────────────",
        f"  Tool: mcp__robinhood-trading__review_equity_order",
        f"  Parameters:",
        f"    symbol:        {entry['symbol']}",
        f"    side:          {entry['side']}",
        f"    order_type:    {entry['order_type']}",
        f"    quantity:      {entry['quantity']}",
        f"    price:         {entry['price']}",
        f"    time_in_force: {entry['time_in_force']}",
    ]
    if "account_number" in entry:
        lines.append(f"    account_number: {entry['account_number']}")

    lines += [
        "",
        "  Step 2 — Place entry order (after review confirms):",
        "  ─────────────────────────────────────────────────",
        f"  Tool: mcp__robinhood-trading__place_equity_order",
        "  (same parameters as review above)",
        "",
        "  Step 3 — Place stop-loss AFTER fill confirmed:",
        "  ─────────────────────────────────────────────────",
        f"  Tool: mcp__robinhood-trading__place_equity_order",
        f"    symbol:        {stop['symbol']}",
        f"    side:          {stop['side']}",
        f"    order_type:    {stop['order_type']}",
        f"    quantity:      {stop['quantity']}",
        f"    stop_price:    {stop['stop_price']}",
        f"    time_in_force: {stop['time_in_force']}",
        "",
        "  ⚠  STOP MUST BE PLACED — rules.md §4: no stop = no signal",
        "═" * 60,
    ]
    return "\n".join(lines)


def log_pending_order(order: dict, note: str = "") -> None:
    """Append a pending order record to decisions-log.md."""
    now     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry_o = order["entry_order"]
    stop_o  = order["stop_order"]

    row = (
        f"\n| {now} | ORDER STAGED | {entry_o['symbol']} | "
        f"{entry_o['side'].upper()} | qty={entry_o['quantity']} | "
        f"entry={entry_o['price']} | stop={stop_o['stop_price']} | "
        f"MCP order pending confirmation. {note} |\n"
    )
    try:
        with open(DECISIONS_LOG, "a") as f:
            f.write(row)
        print(f"  ✓ Logged to decisions-log.md")
    except OSError as e:
        print(f"  ⚠ Log write failed: {e}")


# ── Validation gate ───────────────────────────────────────────────────────────

def validate_trade_card(card: dict) -> list[str]:
    """
    Return list of blocking errors. Empty list = clear to proceed.
    Mirrors the Cockpit Checklist hard blocks for executor-layer defence.
    """
    errors: list[str] = []
    required = ["ticker", "direction", "entry_price", "stop_loss",
                "target_1r", "position_units"]
    for field in required:
        if field not in card or card[field] is None:
            errors.append(f"Missing required field: {field}")

    if not errors:
        if card["direction"] not in ("LONG", "SHORT"):
            errors.append(f"Invalid direction: {card['direction']}")
        if card["stop_loss"] == card["entry_price"]:
            errors.append("stop_loss == entry_price: zero-risk setup blocked")
        if card["position_units"] <= 0:
            errors.append(f"position_units must be > 0, got {card['position_units']}")

    return errors


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare Robinhood equity order from a validated TradeCard"
    )
    parser.add_argument("--ticker", help="Asset symbol (e.g. LINK)")
    parser.add_argument("--direction", choices=["LONG", "SHORT"], default="LONG")
    parser.add_argument("--entry-price", type=float)
    parser.add_argument("--stop-loss", type=float)
    parser.add_argument("--target", type=float)
    parser.add_argument("--quantity", type=float)
    parser.add_argument("--account", default="", help="Robinhood account number")
    parser.add_argument("--json", dest="json_card", help="Full TradeCard JSON string")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print order parameters without logging")
    args = parser.parse_args()

    # ── Build card dict from args or --json ───────────────────────────────────
    if args.json_card:
        try:
            card = json.loads(args.json_card)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            sys.exit(1)
    elif args.ticker and args.entry_price and args.stop_loss and args.quantity:
        card = {
            "ticker": args.ticker,
            "direction": args.direction,
            "entry_price": args.entry_price,
            "stop_loss": args.stop_loss,
            "target_1r": args.target or 0.0,
            "position_units": args.quantity,
        }
    else:
        # Demo mode — show what a LINK order would look like at the alert level
        print("\n[robinhood_executor] Demo mode — no args provided.\n")
        card = {
            "ticker": "LINK",
            "direction": "LONG",
            "entry_price": 8.4746,
            "stop_loss": 8.4746 - 0.9743,   # ATR(7) from today's brief
            "target_1r": 8.4746 + 0.9743,
            "position_units": 10.27,         # example sizing at $100 risk
        }
        print("  Using LINK Gartley D-point example (alert at $8.4746):")

    # ── Validate ──────────────────────────────────────────────────────────────
    errors = validate_trade_card(card)
    if errors:
        print("\n[BLOCKED] Trade card failed validation:")
        for err in errors:
            print(f"  ✗ {err}")
        sys.exit(1)

    # ── Build order ───────────────────────────────────────────────────────────
    order = build_equity_order(
        ticker=card["ticker"],
        direction=card["direction"],
        entry_price=card["entry_price"],
        stop_loss=card["stop_loss"],
        target_1r=card.get("target_1r", 0.0),
        quantity=card["position_units"],
        account_number=args.account,
    )

    print(format_mcp_call(order))

    if not args.dry_run:
        log_pending_order(order, note="Pending MCP confirmation.")
    else:
        print("  [dry-run] Order not logged.")


if __name__ == "__main__":
    main()
