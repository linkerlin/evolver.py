"""ATP CLI subcommands.

Equivalent to ``evolver/src/atp/cli.js``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from evolver.atp.auto_buyer import get_consent, set_consent
from evolver.atp.consumer_agent import check_order, order_and_wait
from evolver.atp.hub_client import list_my_tasks


async def _cmd_buy(args: argparse.Namespace) -> int:
    result = await order_and_wait(
        args.service_id,
        args.budget,
        {"quantity": args.quantity} if args.quantity else None,
        timeout_s=0 if args.no_wait else 300,
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


async def _cmd_orders(_args: argparse.Namespace) -> int:
    result = await list_my_tasks()
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


async def _cmd_status(_args: argparse.Namespace) -> int:
    consent = get_consent()
    enabled = consent.get("enabled") if consent else False
    print(json.dumps({"auto_buyer": "enabled" if enabled else "disabled", "consent": consent}, default=str))
    return 0


async def _cmd_enable(_args: argparse.Namespace) -> int:
    set_consent(True)
    print(json.dumps({"auto_buyer": "enabled"}))
    return 0


async def _cmd_disable(_args: argparse.Namespace) -> int:
    set_consent(False)
    print(json.dumps({"auto_buyer": "disabled"}))
    return 0


def add_atp_subparsers(sub: argparse._SubParsersAction[Any]) -> None:  # type: ignore[name-defined]
    atp_p = sub.add_parser("atp", help="ATP marketplace commands")
    atp_sub = atp_p.add_subparsers(dest="atp_command")

    buy_p = atp_sub.add_parser("buy", help="Buy a service")
    buy_p.add_argument("service_id")
    buy_p.add_argument("--budget", type=float, default=5.0)
    buy_p.add_argument("--quantity", type=int, default=1)
    buy_p.add_argument("--no-wait", action="store_true")

    atp_sub.add_parser("orders", help="List my orders")
    atp_sub.add_parser("status", help="Show ATP status")
    atp_sub.add_parser("enable", help="Enable auto-buyer")
    atp_sub.add_parser("disable", help="Disable auto-buyer")


async def run_atp_command(args: argparse.Namespace) -> int:
    if args.atp_command == "buy":
        return await _cmd_buy(args)
    if args.atp_command == "orders":
        return await _cmd_orders(args)
    if args.atp_command == "status":
        return await _cmd_status(args)
    if args.atp_command == "enable":
        return await _cmd_enable(args)
    if args.atp_command == "disable":
        return await _cmd_disable(args)
    print("Unknown ATP command", file=sys.stderr)
    return 1
