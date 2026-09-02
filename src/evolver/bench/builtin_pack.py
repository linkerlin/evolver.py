"""Built-in deterministic benchmark pack (S26.1 delivery completion).

No Node.js equivalent; evolver.py addition.

Review erratum item 5 shipped only 3 health tasks against the spec's
"22-task benchmark" ambition; this closes the gap with a deterministic,
offline, auto-graded task pack in the repo's own right: 12 tasks across
five families aimed at classic agent failure modes (spec-literal reading,
extraction, code, json navigation, and a trap whose subtlety is asserted at
GENERATION time — bugs must not compensate).

``write_pack(path)`` writes ``tasks.json``; two invocations are
byte-identical (no randomness, no wall-clock). Self-consistency contract:
every task's expected answer, written back into its sandbox, MUST score 1.0
under its own grader (test-pinned for all four graders).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PACK_VERSION = 1


def _spec_tasks() -> list[dict[str, Any]]:
    """Literal-spec formatting: apply ONLY the clauses written."""
    products = [("alpha", "35", "active"), ("beta", "12", "inactive"), ("gamma", "7", "active")]
    return [
        {
            "id": f"spec-pipe-{i}",
            "split": "train" if i < len(products) - 1 else "val",
            "title": f"Format product {products[i][0]} per the pipe spec",
            "prompt": "Read spec.txt and write out.txt with the product fields joined by '|'.",
            "sandbox": {
                "spec.txt": (
                    "Output: <name>|<qty>|<status> — exactly as listed, one product per file.\n"
                )
            },
            "grader": {
                "type": "exact",
                "file": "out.txt",
                "expected": "|".join(products[i]),
            },
        }
        for i in range(len(products))
    ]


def _extract_tasks() -> list[dict[str, Any]]:
    log = (
        "INFO boot ok\n"
        "ERROR disk full on /dev/sda1\n"
        "INFO retry\n"
        "ERROR net timeout host=api.example\n"
        "WARN slow query\n"
    )
    return [
        {
            "id": "extract-errors-val",
            "split": "val",
            "title": "Extract the ERROR lines verbatim",
            "prompt": "Write every line of input.log that starts with ERROR to out.txt, in order.",
            "sandbox": {"input.log": log},
            "grader": {
                "type": "exact",
                "file": "out.txt",
                "expected": "ERROR disk full on /dev/sda1\nERROR net timeout host=api.example",
            },
        },
        {
            "id": "extract-warn-train",
            "split": "train",
            "title": "Does the log mention a slow query?",
            "prompt": (
                "If input.log contains the phrase 'slow query', write 'yes' to out.txt, else 'no'."
            ),
            "sandbox": {"input.log": log},
            "grader": {"type": "exact", "file": "out.txt", "expected": "yes"},
        },
        {
            "id": "extract-host-contains-train",
            "split": "train",
            "title": "Which host timed out?",
            "prompt": "Write the hostname from the timeout ERROR line in input.log to out.txt.",
            "sandbox": {"input.log": log},
            "grader": {
                "type": "contains",
                "file": "out.txt",
                "expected": "api.example",
            },
        },
    ]


def _code_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "code-primes-train",
            "split": "train",
            "title": "Sum the primes below 20",
            "prompt": "Write sum.py that prints the sum of all primes below 20.",
            "sandbox": {"note.txt": "No input files — compute from first principles.\n"},
            "grader": {
                "type": "code_stdout",
                "file": "sum.py",
                "script": "sum.py",
                "expected": "77",
            },
        },
        {
            "id": "code-median-val",
            "split": "val",
            "title": "Median of numbers.txt",
            "prompt": (
                "Write median.py that reads numbers.txt (one integer per "
                "line) and prints the median."
            ),
            "sandbox": {"numbers.txt": "3\n1\n4\n1\n5\n9\n2\n6"},
            "grader": {
                "type": "code_stdout",
                "file": "median.py",
                "script": "median.py",
                "expected": "3",
            },
        },
        {
            "id": "code-wordlen-train",
            "split": "train",
            "title": "Longest word length",
            "prompt": "Write longest.py that prints the length of the longest word in words.txt.",
            "sandbox": {"words.txt": "constantinople\nbrief\nhi\n"},
            "grader": {
                "type": "code_stdout",
                "file": "longest.py",
                "script": "longest.py",
                "expected": "14",
            },
        },
    ]


def _json_tasks() -> list[dict[str, Any]]:
    return [
        {
            "id": "json-nested-val",
            "split": "val",
            "title": "Read the nested status field",
            "prompt": (
                "Inspect data.json, then write out.json as a single JSON object "
                '{"result": "<value of services.db.status>"}.'
            ),
            "sandbox": {"data.json": '{"services": {"db": {"status": "degraded", "latency": 42}}}'},
            "grader": {
                "type": "json_field",
                "file": "out.json",
                "path": "result",
                "expected": "degraded",
            },
        },
    ]


def _trap_tasks() -> list[dict[str, Any]]:
    """Trap: two exclusion clauses whose naive combination looks like one.
    The expected answer is computed at generation time and asserted to differ
    from the single-clause answer — the trap must actually trap (wikiskill
    bench.py:411 discipline: bugs/clauses must not compensate)."""
    names = ["abel", "cain", "eve", "linus", "grep"]
    # clause A: exclude names containing 'e'; clause B: exclude length > 4.
    kept = [n for n in names if "e" not in n and len(n) <= 4]
    only_a = [n for n in names if "e" not in n]
    assert kept not in (only_a, names), "trap clauses compensate — regenerate"
    return [
        {
            "id": "trap-double-exclusion-val",
            "split": "val",
            "title": "Survivors of BOTH exclusions",
            "prompt": (
                "names.txt holds one name per line. Write to out.txt, one per line, "
                "the names that contain NO letter 'e' AND are at most 4 characters "
                "long — both clauses must hold."
            ),
            "sandbox": {"names.txt": "\n".join(names)},
            "grader": {"type": "exact", "file": "out.txt", "expected": "\n".join(kept)},
        },
        {
            "id": "trap-literal-count-train",
            "split": "train",
            "title": "Count by the dozen, literally",
            "prompt": (
                "items.txt lists item names. The spec counts items by the DOZEN "
                "(1 dozen = 12). Write the whole-dozen count (integer) to out.txt — "
                "leftover items do not count."
            ),
            "sandbox": {"items.txt": "\n".join(f"item{i}" for i in range(30))},
            "grader": {"type": "exact", "file": "out.txt", "expected": "2"},
        },
    ]


def build_pack() -> list[dict[str, Any]]:
    """Deterministic built-in pack (12 tasks; byte-identical across calls)."""
    tasks = _spec_tasks() + _extract_tasks() + _code_tasks() + _json_tasks() + _trap_tasks()
    from evolver.bench.tasks import validate_tasks

    errors = validate_tasks(tasks)
    if errors:  # pragma: no cover - generation bug guard
        raise ValueError("built-in pack invalid: " + "; ".join(errors))
    return tasks


def write_pack(path: Path) -> Path:
    tasks = build_pack()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pack_version": PACK_VERSION, "tasks": tasks}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path


def load_builtin_tasks(raw: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Accept both the wrapped {pack_version, tasks} file and a bare list."""
    if isinstance(raw, dict) and isinstance(raw.get("tasks"), list):
        return list(raw["tasks"])
    if isinstance(raw, list):
        return list(raw)
    raise ValueError("pack file must be a task list or {'pack_version', 'tasks'}")


__all__ = ["PACK_VERSION", "build_pack", "load_builtin_tasks", "write_pack"]
