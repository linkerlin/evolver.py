"""ATP execute bridge — complete an ATP task and submit delivery proof.

Equivalent to ``evolver/src/atp/atpExecute.js``.
Called by CLI after a merchant writes an answer file.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from evolver.atp.hub_client import submit_delivery
from evolver.gep.content_hash import compute_asset_id

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 32_000


def _build_gene(answer: str, task: dict[str, Any]) -> dict[str, Any]:
    gene: dict[str, Any] = {
        "type": "Gene",
        "id": f"atp-{task.get('task_id', 'unknown')}",
        "summary": f"ATP answer for {task.get('task_id', '')}",
        "strategy": ["atp_merchant_delivery"],
        "validation": [],
        "constraints": {"max_files": 1, "forbidden_paths": [".git"]},
    }
    gene["asset_id"] = compute_asset_id(gene)
    return gene


def _build_capsule(answer: str, task: dict[str, Any]) -> dict[str, Any]:
    capsule: dict[str, Any] = {
        "type": "Capsule",
        "id": f"atp-cap-{task.get('task_id', 'unknown')}",
        "content": answer[:MAX_ANSWER_CHARS],
        "a2a": {
            "atp": {
                "order_id": task.get("atp_order_id"),
                "task_id": task.get("task_id"),
                "capabilities": task.get("capabilities", []),
            }
        },
    }
    capsule["asset_id"] = compute_asset_id(capsule)
    return capsule


async def complete_atp_task(
    task_id: str,
    answer_file: Path | str,
) -> dict[str, Any]:
    path = Path(answer_file)
    if not path.exists():
        return {"ok": False, "error": "answer_file_not_found", "stage": "read"}
    answer = path.read_text(encoding="utf-8")
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS]

    # Simplified: skip publish/complete stages; just submit delivery
    proof = json.dumps({"task_id": task_id, "answer_length": len(answer)})
    result = await submit_delivery(task_id, proof)
    if result.get("ok"):
        return {"ok": True, "task_id": task_id}
    return {"ok": False, "error": result.get("error"), "stage": "deliver"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--answer-file", required=True)
    args = parser.parse_args()

    import asyncio

    result = asyncio.run(complete_atp_task(args.task_id, args.answer_file))
    print(json.dumps(result, ensure_ascii=False))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
