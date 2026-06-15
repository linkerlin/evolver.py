"""ATP CLI subcommands — full marketplace command surface.

Equivalent to ``evolver/src/atp/cli.js`` (327 lines).

Subcommands:
  atp status              — show auto-buyer mode, balance, orders
  atp enable / disable    — toggle auto-buyer
  atp buy <svc> [opts]    — order a service and optionally wait for delivery
  atp orders              — list my orders
  atp tasks               — list available/open tasks
  atp claim <task_id>     — claim a task
  atp deliver <order_id>  — submit a delivery proof
  atp settle <order_id>   — manually settle an order
  atp dispute <order_id>  — dispute an order
  atp publish             — publish a service listing
  atp policy              — show ATP policy
  atp proofs [--order-id] — list delivery proofs
  atp tier [merchant_id]  — query merchant tier
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evolver.atp.auto_buyer import get_consent, set_consent
from evolver.atp.consumer_agent import order_and_wait
from evolver.atp.hub_client import (
    claim_task,
    dispute_order,
    get_atp_policy,
    get_merchant_tier,
    get_order_status,
    list_my_tasks,
    list_open_tasks,
    list_proofs,
    publish_service,
    settle_order,
    submit_delivery,
)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, default=str, indent=2))


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def _cmd_buy(args: argparse.Namespace) -> int:
    result = await order_and_wait(
        args.service_id,
        args.budget,
        {"quantity": args.quantity} if args.quantity else None,
        timeout_s=0 if args.no_wait else 300,
    )
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_orders(_args: argparse.Namespace) -> int:
    result = await list_my_tasks()
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_tasks(_args: argparse.Namespace) -> int:
    result = await list_open_tasks()
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_claim(args: argparse.Namespace) -> int:
    result = await claim_task(args.task_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_deliver(args: argparse.Namespace) -> int:
    proof = args.proof
    if args.proof_file:
        proof = Path(args.proof_file).read_text(encoding="utf-8")
    result = await submit_delivery(args.order_id, proof, result_asset_id=args.asset_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_settle(args: argparse.Namespace) -> int:
    result = await settle_order(args.order_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_dispute(args: argparse.Namespace) -> int:
    result = await dispute_order(args.order_id, args.reason)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_publish(args: argparse.Namespace) -> int:
    spec_file = Path(args.spec)
    if not spec_file.exists():
        print(f"Service spec not found: {spec_file}", file=sys.stderr)
        return 1
    service = json.loads(spec_file.read_text(encoding="utf-8"))
    result = await publish_service(service)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_policy(_args: argparse.Namespace) -> int:
    result = await get_atp_policy()
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_proofs(args: argparse.Namespace) -> int:
    result = await list_proofs(order_id=args.order_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_tier(args: argparse.Namespace) -> int:
    result = await get_merchant_tier(merchant_id=args.merchant_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_order_status(args: argparse.Namespace) -> int:
    result = await get_order_status(args.order_id)
    _print_json(result)
    return 0 if result.get("ok") else 1


async def _cmd_status(_args: argparse.Namespace) -> int:
    consent = get_consent()
    enabled = consent.get("enabled") if consent else False
    _print_json(
        {"auto_buyer": "enabled" if enabled else "disabled", "consent": consent}
    )
    return 0


async def _cmd_enable(_args: argparse.Namespace) -> int:
    set_consent(True)
    _print_json({"auto_buyer": "enabled"})
    return 0


async def _cmd_disable(_args: argparse.Namespace) -> int:
    set_consent(False)
    _print_json({"auto_buyer": "disabled"})
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def add_atp_subparsers(sub: Any) -> None:
    """Register all ATP subcommands on the given argparse subparser."""
    atp_p = sub.add_parser("atp", help="ATP marketplace commands")
    atp_sub = atp_p.add_subparsers(dest="atp_command")

    # Status / toggle
    atp_sub.add_parser("status", help="Show ATP status (mode, balance, orders)")
    atp_sub.add_parser("enable", help="Enable auto-buyer")
    atp_sub.add_parser("disable", help="Disable auto-buyer")

    # Buy
    buy_p = atp_sub.add_parser("buy", help="Order a service")
    buy_p.add_argument("service_id", help="Service ID to purchase")
    buy_p.add_argument("--budget", type=float, default=5.0, help="Max ATP budget")
    buy_p.add_argument("--quantity", type=int, default=1)
    buy_p.add_argument("--no-wait", action="store_true", help="Return immediately")

    # Orders / tasks
    atp_sub.add_parser("orders", help="List my orders/tasks")
    atp_sub.add_parser("tasks", help="List available open tasks")

    claim_p = atp_sub.add_parser("claim", help="Claim a task")
    claim_p.add_argument("task_id")

    # Delivery lifecycle
    deliver_p = atp_sub.add_parser("deliver", help="Submit a delivery proof")
    deliver_p.add_argument("order_id")
    deliver_p.add_argument("--proof", default="", help="Inline proof text")
    deliver_p.add_argument("--proof-file", help="Path to proof file")
    deliver_p.add_argument("--asset-id", help="Result asset ID")

    settle_p = atp_sub.add_parser("settle", help="Manually settle an order")
    settle_p.add_argument("order_id")

    dispute_p = atp_sub.add_parser("dispute", help="Dispute an order")
    dispute_p.add_argument("order_id")
    dispute_p.add_argument("--reason", required=True)

    # Service publishing
    pub_p = atp_sub.add_parser("publish", help="Publish a service listing")
    pub_p.add_argument("spec", help="Path to service spec JSON")

    # Info queries
    atp_sub.add_parser("policy", help="Show ATP policy")
    proofs_p = atp_sub.add_parser("proofs", help="List delivery proofs")
    proofs_p.add_argument("--order-id", default=None)

    tier_p = atp_sub.add_parser("tier", help="Query merchant tier")
    tier_p.add_argument("merchant_id", nargs="?", default=None)

    status_p = atp_sub.add_parser("order", help="Show order status")
    status_p.add_argument("order_id")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_COMMAND_MAP: dict[str, Any] = {
    "buy": _cmd_buy,
    "orders": _cmd_orders,
    "tasks": _cmd_tasks,
    "claim": _cmd_claim,
    "deliver": _cmd_deliver,
    "settle": _cmd_settle,
    "dispute": _cmd_dispute,
    "publish": _cmd_publish,
    "policy": _cmd_policy,
    "proofs": _cmd_proofs,
    "tier": _cmd_tier,
    "order": _cmd_order_status,
    "status": _cmd_status,
    "enable": _cmd_enable,
    "disable": _cmd_disable,
}


async def run_atp_command(args: argparse.Namespace) -> int:
    """Dispatch an ATP subcommand. Returns exit code."""
    handler = _COMMAND_MAP.get(args.atp_command)
    if handler is None:
        print(f"Unknown ATP command: {args.atp_command}", file=sys.stderr)
        print(
            "Available: " + ", ".join(sorted(_COMMAND_MAP.keys())), file=sys.stderr
        )
        return 1
    return int(await handler(args))


__all__ = ["add_atp_subparsers", "run_atp_command"]
