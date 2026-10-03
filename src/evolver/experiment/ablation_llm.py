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

from evolver.experiment.ablation import ablation_verdict, run_ablation, run_stage_exit
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


def run_llm_stage_exit(
    tasks: list[dict[str, Any]],
    record_context: str,
    *,
    model: str = DEFAULT_ABLATION_MODEL,
    max_tokens: int = DEFAULT_ABLATION_MAX_TOKENS,
    budget: int | None = None,
    success_mode: str = "contains",
    timeout_s: int = 120,
    control_context: str = "",
    order_seed: int = 0,
    temperature: float | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Stage-exit ablation with a real LLM: seeded interleaving + call records.

    Same honesty rules as :func:`run_llm_ablation`, plus: the sampling params
    are frozen for the run and recorded in ``sampling`` (``None`` = provider
    default, recorded as such — never guessed), and every call's served model
    id lands in its call record in execution order. The usage split the
    provider reports flows through the agent protocol into each call record,
    so the prompt-token balance is measured, not assumed from char length.
    """
    client = DeepSeekClient(
        model=model,
        max_tokens=max_tokens,
        timeout_s=timeout_s,
        temperature=temperature,
        seed=seed,
    )
    if not client.api_key:
        raise LLMError("no DEEPSEEK_API_KEY configured")
    errors: list[dict[str, str]] = []
    server_models: set[str] = set()
    # One entry per agent invocation, in execution order — _run_one calls the
    # agent exactly once per call, so this aligns with report["calls"] by seq.
    # Failures append "" before re-raising so the alignment never shifts.
    per_call_server: list[str] = []

    def agent_fn(prompt: str, context: str) -> tuple[str, dict[str, int]]:
        try:
            answer, usage = client.complete_prompt(prompt, context=context, max_tokens=max_tokens)
        except Exception:
            per_call_server.append("")
            raise
        served = client.last_server_model
        if served:
            server_models.add(served)
        per_call_server.append(served)
        return answer, usage

    def on_error(task_id: str, arm: str, error: str) -> None:
        errors.append({"task_id": task_id, "arm": arm, "error": error[:300]})

    report = run_stage_exit(
        tasks,
        record_context=record_context,
        agent_fn=agent_fn,
        budget=budget,
        success_mode=success_mode,
        on_task_error=on_error,
        control_context=control_context,
        order_seed=order_seed,
    )
    for call, served in zip(report["calls"], per_call_server, strict=True):
        call["server_model"] = served
    return {
        "model_requested": model,
        "server_models": sorted(server_models),
        "sampling": {
            "temperature": temperature if temperature is not None else "provider-default",
            "seed": seed,
            "max_tokens": max_tokens,
            "timeout_s": timeout_s,
        },
        "budget": report["budget"],
        "control": report["control"],
        "order_seed": report["order_seed"],
        "task_digest": report["task_digest"],
        "schedule": report["schedule"],
        "calls": report["calls"],
        "paired": report["paired"],
        "prompt_token_balance": report["prompt_token_balance"],
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
    "run_llm_stage_exit",
]
