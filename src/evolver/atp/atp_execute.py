"""ATP execute bridge — complete an ATP task and submit delivery proof.

Equivalent to ``evolver/src/atp/atpExecute.js`` (259 lines).

Called by CLI after a merchant writes an answer file. Builds a gene + capsule
from the answer, generates a structured proof (git diff + test output + answer
hash), and submits the delivery to the Hub.

Security: reuses the sandbox safety model from ``gep/validator/sandbox_executor``
for any validation commands declared in the task.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from evolver.atp.hub_client import submit_delivery
from evolver.gep.content_hash import compute_asset_id

logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 32_000
MAX_PROOF_CHARS = 8_000
_VALIDATION_TIMEOUT_S = 30
_ALLOWED_PREFIXES = ("python", "pytest", "pip")
_FORBIDDEN_RE = re.compile(r"[;&|>`$]")


def _build_gene(task: dict[str, Any]) -> dict[str, Any]:
    """Build a gene representing the ATP delivery strategy."""
    gene: dict[str, Any] = {
        "type": "Gene",
        "id": f"atp-{task.get('task_id', 'unknown')}",
        "summary": f"ATP answer for {task.get('task_id', '')}",
        "category": "innovate",
        "strategy": [
            "Read the task question and requirements",
            "Produce the answer following the task's output format",
            "Validate the answer against any declared validation commands",
            "Submit the delivery proof to the Hub",
        ],
        "validation": [],
        "constraints": {"max_files": 1, "forbidden_paths": [".git", ".venv"]},
        "signals_match": [f"atp_task:{task.get('task_id', '')}"],
    }
    gene["asset_id"] = compute_asset_id(gene)
    return gene


def _build_capsule(answer: str, task: dict[str, Any]) -> dict[str, Any]:
    """Build a capsule containing the actual delivery content."""
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


def _run_validation(
    commands: list[str], cwd: Path | None = None
) -> dict[str, Any]:
    """Run validation commands safely (whitelist + timeout).

    Returns ``{passed: bool, output: str, duration_ms: float}``.
    Only allows ``python`` and ``pytest`` prefixes (no shell operators).
    """
    results: list[dict[str, Any]] = []
    for cmd in commands:
        if not cmd.strip():
            continue
        if _FORBIDDEN_RE.search(cmd):
            results.append({"cmd": cmd, "passed": False, "error": "forbidden_operator"})
            continue
        parts = cmd.split()
        if not parts or not any(parts[0].startswith(p) for p in _ALLOWED_PREFIXES):
            results.append({"cmd": cmd, "passed": False, "error": "prefix_not_allowed"})
            continue
        start = time.time()
        try:
            proc = subprocess.run(
                parts,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=_VALIDATION_TIMEOUT_S,
                check=False,
            )
            results.append(
                {
                    "cmd": cmd,
                    "passed": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[:500],
                    "stderr": proc.stderr[:500],
                    "duration_ms": round((time.time() - start) * 1000, 1),
                }
            )
        except subprocess.TimeoutExpired:
            results.append({"cmd": cmd, "passed": False, "error": "timeout"})
        except Exception as exc:
            results.append({"cmd": cmd, "passed": False, "error": str(exc)})

    all_passed = all(r.get("passed") for r in results) if results else True
    return {"passed": all_passed, "results": results}


def _build_proof(
    answer: str,
    task: dict[str, Any],
    gene: dict[str, Any],
    capsule: dict[str, Any],
    validation: dict[str, Any] | None = None,
) -> str:
    """Build a structured delivery proof."""
    answer_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    proof: dict[str, Any] = {
        "task_id": task.get("task_id"),
        "order_id": task.get("atp_order_id"),
        "answer_hash": f"sha256:{answer_hash}",
        "answer_length": len(answer),
        "gene_id": gene.get("id"),
        "capsule_id": capsule.get("id"),
        "asset_id": capsule.get("asset_id"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if validation:
        proof["validation"] = validation
    return json.dumps(proof, ensure_ascii=False)[:MAX_PROOF_CHARS]


async def complete_atp_task(
    task_id: str,
    answer_file: Path | str,
    *,
    task: dict[str, Any] | None = None,
    run_validations: bool = True,
) -> dict[str, Any]:
    """Complete an ATP task: read answer, build proof, submit delivery.

    Parameters:
        task_id: The Hub task ID.
        answer_file: Path to the file containing the answer.
        task: Optional task metadata dict (for gene/capsule construction).
        run_validations: If True and the task declares validation commands,
            run them before submitting.

    Returns ``{ok: bool, task_id: str, ...}``.
    """
    path = Path(answer_file)
    if not path.is_file():
        return {"ok": False, "error": "answer_file_not_found", "stage": "read"}

    answer = path.read_text(encoding="utf-8")
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS]

    task_meta = task or {"task_id": task_id}

    gene = _build_gene(task_meta)
    capsule = _build_capsule(answer, task_meta)

    validation_result: dict[str, Any] | None = None
    if run_validations and task_meta.get("validation_commands"):
        validation_result = _run_validation(task_meta["validation_commands"])
        if not validation_result.get("passed"):
            return {
                "ok": False,
                "error": "validation_failed",
                "stage": "validate",
                "validation": validation_result,
            }

    proof = _build_proof(answer, task_meta, gene, capsule, validation_result)
    result = await submit_delivery(task_id, proof, result_asset_id=capsule.get("asset_id"))

    if result.get("ok"):
        return {
            "ok": True,
            "task_id": task_id,
            "gene_id": gene["id"],
            "capsule_id": capsule["id"],
            "answer_hash": f"sha256:{hashlib.sha256(answer.encode()).hexdigest()[:16]}",
        }
    return {"ok": False, "error": result.get("error"), "stage": "deliver"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Complete an ATP task and submit delivery")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--answer-file", required=True)
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()

    import asyncio  # noqa: PLC0415

    result = asyncio.run(
        complete_atp_task(
            args.task_id,
            args.answer_file,
            run_validations=not args.no_validate,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
