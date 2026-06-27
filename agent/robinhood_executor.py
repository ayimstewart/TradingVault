"""
robinhood_executor.py — Prepare and log Robinhood equity orders.

Translates a validated TradeCard (from position_sizer.py) into a
structured order payload, validates it, and logs it to decisions-log.md.

STOCKS ONLY for semi-auto staging — Human confirms before execution.
Crypto auto-execute is flagged pending until MCP execution tools are wired.

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

    MCP schema (review_equity_order / place_equity_order):
      symbol, side, amount, quantity, order_type, limit_price, time_in_force

    Stop-loss is a SEPARATE order after fill — not in MCP bracket schema.
    """
    side = "buy" if direction == "LONG" else "sell"
    stop_side = "sell" if direction == "LONG" else "buy"

    entry_order = {
        "symbol": ticker,
        "side": side,
        "order_type": order_type,
        "quantity": round(quantity, 6),
        "limit_price": round(entry_price, 6),
        "time_in_force": time_in_force,
    }
    if account_number:
        entry_order["account_number"] = account_number

    # Staged separately — place after entry fill confirmed (human or future MCP)
    stop_order = {
        "symbol": ticker,
        "side": stop_side,
        "order_type": "stop",
        "quantity": round(quantity, 6),
        "stop_loss_price": round(stop_loss, 6),
        "time_in_force": "gtc",
        "note": "Separate order — not part of place_equity_order MCP params",
    }
    if account_number:
        stop_order["account_number"] = account_number

    return {
        "entry_order": entry_order,
        "stop_order":  stop_order,
        "target_1r":   target_1r,
    }


def format_mcp_call(order: dict) -> str:
    """
    Print the exact Claude Code MCP tool invocation to execute this order.
    Human confirms before execution (stocks semi-auto).
    """
    entry = order["entry_order"]
    stop  = order["stop_order"]

    lines = [
        "\n" + "═" * 60,
        "  ROBINHOOD EXECUTOR — MCP CALL PARAMETERS",
        "  Human confirms before execution.",
        "═" * 60,
        "",
        "  Step 1 — Review entry order (run first):",
        "  ─────────────────────────────────────────",
        "  Tool: mcp__robinhood-trading__review_equity_order",
        "  Parameters:",
        f"    symbol:        {entry['symbol']}",
        f"    side:          {entry['side']}",
        f"    order_type:    {entry['order_type']}",
        f"    quantity:      {entry['quantity']}",
        f"    limit_price:   {entry['limit_price']}",
        f"    time_in_force: {entry['time_in_force']}",
    ]
    if "account_number" in entry:
        lines.append(f"    account_number: {entry['account_number']}")

    lines += [
        "",
        "  Step 2 — Place entry order (after human confirms review):",
        "  ─────────────────────────────────────────────────────────",
        "  Tool: mcp__robinhood-trading__place_equity_order",
        "  (same parameters as review above — limit_price, not price)",
        "",
        "  Step 3 — Stop-loss AFTER fill (separate order; not in MCP bracket):",
        "  ─────────────────────────────────────────────────────────────────",
        f"    symbol:           {stop['symbol']}",
        f"    side:             {stop['side']}",
        f"    quantity:         {stop['quantity']}",
        f"    stop_loss_price:  {stop['stop_loss_price']}  (place via app or future MCP)",
        f"    time_in_force:    {stop['time_in_force']}",
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
        f"entry={entry_o['limit_price']} | stop={stop_o['stop_loss_price']} | "
        f"{note} |\n"
    )
    try:
        with open(DECISIONS_LOG, "a") as f:
            f.write(row)
        print("  ✓ Logged to decisions-log.md")
    except OSError as e:
        print(f"  ⚠ Log write failed: {e}")


def stage_for_review(order: dict, note: str = "") -> dict:
    """
    STOCKS ONLY — semi-auto: print MCP params and log for human confirmation.
    Human confirms before execution.
    """
    print(format_mcp_call(order))
    log_pending_order(
        order,
        note=note or "STAGED — Human confirms before execution.",
    )
    return {"status": "staged_for_review", "order": order}


def auto_execute(order: dict, note: str = "") -> dict:
    """
    Crypto full-auto path — pending until MCP execution tools are available.
    Does not submit unattended; logs as pending auto-execute.
    """
    print(format_mcp_call(order))
    print(
        "  CRYPTO AUTO-EXECUTE: PENDING — MCP place_equity_order not wired "
        "for unattended submit yet."
    )
    log_pending_order(
        order,
        note=note or "PENDING auto-execute — awaiting MCP execution tools.",
    )
    return {"status": "pending_auto", "order": order}


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


def order_from_signal(sig, quantity: float) -> dict:
    """Build order dict from a SignalResult + sized quantity."""
    return build_equity_order(
        ticker=sig.ticker,
        direction=sig.signal_type.value,
        entry_price=sig.entry_price,
        stop_loss=sig.stop_loss,
        target_1r=sig.target_1r,
        quantity=quantity,
    )


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
        print("\n[robinhood_executor] Demo mode — no args provided.\n")
        card = {
            "ticker": "LINK",
            "direction": "LONG",
            "entry_price": 8.4746,
            "stop_loss": 8.4746 - 0.9743,
            "target_1r": 8.4746 + 0.9743,
            "position_units": 10.27,
        }
        print("  Using LINK Gartley D-point example (alert at $8.4746):")

    errors = validate_trade_card(card)
    if errors:
        print("\n[BLOCKED] Trade card failed validation:")
        for err in errors:
            print(f"  ✗ {err}")
        sys.exit(1)

    order = build_equity_order(
        ticker=card["ticker"],
        direction=card["direction"],
        entry_price=card["entry_price"],
        stop_loss=card["stop_loss"],
        target_1r=card.get("target_1r", 0.0),
        quantity=card["position_units"],
        account_number=args.account,
    )

    if args.dry_run:
        print(format_mcp_call(order))
        print("  [dry-run] Order not logged.")
        return

    stage_for_review(order)


if __name__ == "__main__":
    main()
