"""Real-LLM ablation runner (经验即证据 §5.9) — the agent is deepseek-flash.

Wires :class:`~evolver.experiment.llm.DeepSeekClient` into
:func:`~evolver.experiment.ablation.run_ablation`: same tasks, same budget,
with-records vs without-records, ``success_mode="contains"`` for
LLM-generated code.

Two honesty rules live here:

1. The model id is pinned explicitly by the caller — never inherited
   silently from ``DEEPSEEK_MODEL`` — and the *server-returned* model id is
   recorded in the report, so the label can never drift from what ran.
2. An LLM failure is per-task (failed task + error entry), never a crashed
   run: one bad call must not erase the other arm's evidence.
"""

from __future__ import annotations

from typing import Any, Final

from evolver.experiment.ablation import ablation_verdict, run_ablation
from evolver.experiment.llm import DeepSeekClient, LLMError

#: The model the stage's real-LLM ablation runs on. Pinned explicitly at the
#: call site — never read from ``DEEPSEEK_MODEL`` here — so the report label
#: cannot drift from what actually ran.
DEFAULT_ABLATION_MODEL: Final = "deepseek-flash"
#: Reasoning models spend tokens before answering; leave headroom.
DEFAULT_ABLATION_MAX_TOKENS: Final = 16384


def run_llm_ablation(
    tasks: list[dict[str, Any]],
    record_context: str,
    *,
    model: str = DEFAULT_ABLATION_MODEL,
    max_tokens: int = DEFAULT_ABLATION_MAX_TOKENS,
    budget: int | None = None,
    success_mode: str = "contains",
    timeout_s: int = 120,
    control_context: str = "",
) -> dict[str, Any]:
    """Run the with/without-records ablation with a real LLM as the agent.

    Returns the metrics report plus ``model_requested``, ``server_models``
    (ids the provider actually served), ``verdict``, and per-task ``errors``.
    Raises :class:`LLMError` before any call when no API key is configured.
    """
    client = DeepSeekClient(model=model, max_tokens=max_tokens, timeout_s=timeout_s)
    if not client.api_key:
        raise LLMError("no DEEPSEEK_API_KEY configured")
    errors: list[dict[str, str]] = []
    server_models: set[str] = set()

    def agent_fn(prompt: str, context: str) -> tuple[str, int]:
        answer, usage = client.complete_prompt(prompt, context=context, max_tokens=max_tokens)
        if client.last_server_model:
            server_models.add(client.last_server_model)
        return answer, usage.get("total_tokens", 0)

    def on_error(task_id: str, arm: str, error: str) -> None:
        errors.append({"task_id": task_id, "arm": arm, "error": error[:300]})

    report = run_ablation(
        tasks,
        record_context=record_context,
        agent_fn=agent_fn,
        budget=budget,
        success_mode=success_mode,
        on_task_error=on_error,
        control_context=control_context,
    )
    return {
        "model_requested": model,
        "server_models": sorted(server_models),
        "budget": report["budget"],
        "control": report["control"],
        "with_records": report["with_records"],
        "without_records": report["without_records"],
        "comparison": report["comparison"],
        "verdict": ablation_verdict(report),
        "errors": errors,
    }


__all__ = [
    "DEFAULT_ABLATION_MAX_TOKENS",
    "DEFAULT_ABLATION_MODEL",
    "run_llm_ablation",
]
