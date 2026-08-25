"""Self A/B acceptance — evolver.py A/B harness + thesis statistics self-test.

Sprint 24.11: verify the experiment stack end-to-end (run_comparison →
metrics → evaluate_thesis) with a DETERMINISTIC mock agent — no LLM, no
cost, no keys. Two scenarios:

- ``gene_effect``   the weak agent answers better when a matching gene is
                    injected ⇒ the thesis verdict MUST be ``evolved_better``
- ``no_effect``     the agent ignores context ⇒ the thesis verdict MUST NOT
                    be ``evolved_better`` (no false positive)

The mock agent: solves a task iff (a) a gene whose summary carries the
task's requirement token was injected, and (b) a seeded random roll lands
in the "gene helps" band; plus a small luck floor. This reproduces the
real-world shape of "documented strategy raises solve rate" without any
network call.

Run:  uv run python scripts/self_ab_acceptance.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Any

from evolver.experiment.comparison import run_comparison

REPO = Path(__file__).resolve().parents[1]
SEED = 42
N_TASKS = 30
MATCHED = 20  # tasks whose requirement token appears in a gene summary
GENE_HIT_RATE = 0.85
LUCK_RATE = 0.15

#: Requirement tokens paired with the gene that documents them.
GENE_KNOWLEDGE: dict[str, str] = {
    "import": "Always start by running the linter to surface missing imports",
    "timeout": "Raise the request timeout to 120s for slow upstream services",
    "retry": "Retry transient failures with exponential backoff, max 3 attempts",
    "sql": "Wrap every query in a transaction and use parameterized bindings",
    "logging": "Add structured logging at every boundary before debugging",
}


def make_tasks() -> list[dict[str, Any]]:
    tokens = list(GENE_KNOWLEDGE)
    tasks: list[dict[str, Any]] = []
    for i in range(N_TASKS):
        token = tokens[i % len(tokens)]
        matched = i < MATCHED
        tasks.append(
            {
                "id": f"t{i:02d}",
                "prompt": f"Fix the failing {token}-related issue in the module.",
                "expected": f"solved {token}",
                "_token": token,
                "_matched": matched,
            }
        )
    return tasks


def make_genes() -> list[dict[str, Any]]:
    return [
        {
            "id": f"gene_{token}",
            "summary": GENE_KNOWLEDGE[token],
            "strategy": [f"apply the {token} strategy", "verify with tests"],
        }
        for token in GENE_KNOWLEDGE
    ]


def make_agent(use_genes: bool) -> Any:
    rng = random.Random(SEED)

    def agent_fn(prompt: str, context: str) -> tuple[str, int]:
        token = next((t for t in GENE_KNOWLEDGE if t in prompt), "none")
        has_gene = use_genes and token != "none" and token in context
        if has_gene and rng.random() < GENE_HIT_RATE:
            return f"solved {token} via documented strategy", 1200
        if rng.random() < LUCK_RATE:
            return f"solved {token} by luck", 900
        return "no solution found", 800

    return agent_fn


def run_scenario(name: str, use_genes: bool) -> dict[str, Any]:
    tasks = make_tasks()
    genes = make_genes() if use_genes else None
    result = run_comparison(tasks, genes=genes, agent_fn=make_agent(use_genes))
    thesis = result["thesis"]
    return {
        "scenario": name,
        "baseline": result["baseline_metrics"],
        "evolved": result["evolved_metrics"],
        "thesis": thesis,
    }


def main() -> int:
    scenarios = [
        run_scenario("gene_effect", use_genes=True),
        run_scenario("no_effect", use_genes=False),
    ]
    report = {"tool": "evolver.py self A/B acceptance", "scenarios": scenarios}

    ok = True
    for s in scenarios:
        verdict = s["thesis"]["verdict"]
        name = s["scenario"]
        baseline_rate = s["baseline"]["success_rate"]
        evolved_rate = s["evolved"]["success_rate"]
        print(
            f"[{name}] baseline={baseline_rate:.2f} evolved={evolved_rate:.2f} "
            f"verdict={verdict} p={s['thesis']['p_value']} power={s['thesis']['achieved_power']}"
        )
        if name == "gene_effect" and verdict != "evolved_better":
            ok = False
            print(f"  FAIL: expected evolved_better, got {verdict}")
        if name == "no_effect" and verdict == "evolved_better":
            ok = False
            print(f"  FAIL: false positive — {verdict}")

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("self_ab_report.json")
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report: {out}")
    print("SELF A/B ACCEPTANCE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
