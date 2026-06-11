#!/usr/bin/env python3
"""Local ATP loop demo — buyer tick, deliver, heartbeat signals (mocked Hub)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

_WORKSPACE = Path(__file__).resolve().parent / "workspace"
os.environ.setdefault("OPENCLAW_WORKSPACE", str(_WORKSPACE))
os.environ.setdefault("EVOLVER_NO_PARENT_GIT", "1")
os.environ.setdefault("MEMORY_DIR", str(_WORKSPACE / "memory"))
_WORKSPACE.mkdir(parents=True, exist_ok=True)
(_WORKSPACE / "memory").mkdir(parents=True, exist_ok=True)


async def main() -> int:
    from evolver.atp import auto_buyer, auto_deliver, heartbeat_signals_handler

    auto_buyer.set_consent(True)

    async def fake_place(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {"ok": True, "data": {"order_id": "ord_demo_1"}}

    async def fake_submit(order_id: str, proof: str, asset_id: str | None = None) -> dict[str, Any]:
        print(f"  [submit_delivery] order={order_id} asset={asset_id}")
        return {"ok": True}

    import evolver.atp.auto_buyer as ab
    import evolver.atp.auto_deliver as ad
    import evolver.atp.heartbeat_signals_handler as hb

    ab.place_order = fake_place  # type: ignore[method-assign]
    ad.submit_delivery = fake_submit  # type: ignore[method-assign]
    hb.submit_delivery = fake_submit  # type: ignore[method-assign]

    print("=== 1. Auto-buyer run_tick ===")
    buy = await auto_buyer.run_tick(["pytest failed with TypeError"])
    print(buy)

    print("\n=== 2. Auto-deliver claimed task ===")
    deliver = auto_deliver.AutoDeliver()
    await deliver._handle_task(
        {
            "atp_order_id": "ord_claim_demo",
            "status": "claimed",
            "task_id": "task_demo",
            "title": "Code review",
        }
    )

    print("\n=== 3. Heartbeat signals ===")
    heartbeat_signals_handler._LAST_RUN_AT = 0.0
    summary = await heartbeat_signals_handler.handle_signals(
        {
            "signals": ["lint error in module"],
            "pending_deliveries": [
                {"order_id": "ord_hb_1", "result_asset_id": "asset_hb_1"},
            ],
        }
    )
    print(summary)

    print("\nDemo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
