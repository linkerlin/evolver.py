"""MCP server — thin tool surface over existing engine modules.

Concept harvest from Node v2 ``evolver-mcp`` (asset.search/fetch/publish,
gep.build, mailbox.*; behavioral re-implementation, no code copied).
Python-side minimal slice (Sprint 24.7, 演进方案.md §9 概念收割 #5):

- ``asset_search`` / ``asset_get`` — local-first GEP asset lookup
- ``mailbox_send`` / ``mailbox_poll`` / ``mailbox_ack`` — durable
  agent↔daemon messages (reuses the proxy MailboxStore)
- ``rebuild_views`` / ``cycle_timeline`` — Sprint 24.1 event projections

The core engine never calls an LLM through these tools; they expose
read/coordination operations to MCP clients (Claude Code, opencode, ...).
Run with ``evolver mcp`` (stdio transport).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, Literal

from evolver.proxy.mailbox.store import MailboxStore


def _mailbox_dir() -> Path:
    from evolver.gep.paths import get_mailbox_dir

    return get_mailbox_dir()


def _mailbox_store() -> MailboxStore:
    return MailboxStore(_mailbox_dir())


# ---------------------------------------------------------------------------
# Assets (local-first; no Hub calls)
# ---------------------------------------------------------------------------


def _local_assets() -> list[tuple[str, dict[str, Any]]]:
    from evolver.gep.asset_store import load_capsules, load_genes

    return [
        *[("gene", g) for g in load_genes()],
        *[("capsule", c) for c in load_capsules()],
    ]


def asset_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search local Genes/Capsules by token-AND over id/name/summary/signals.

    Tool-check finding (2026-09-05): the old whole-string substring match made
    multi-word queries ("hub retry") silently empty, and `summary` /
    `signals_match` — a Gene's primary text — were not searched at all.
    """
    needles = [t.casefold() for t in query.strip().split() if t]
    matches: list[dict[str, Any]] = []
    if not needles:
        return matches
    for kind, asset in _local_assets():
        haystack = " ".join(
            str(asset.get(field) or "")
            for field in ("id", "name", "description", "summary", "category", "title")
        ).casefold()
        signals = asset.get("signals_match")
        if isinstance(signals, list):
            haystack += " " + " ".join(str(s) for s in signals)
        if all(n in haystack for n in needles):
            matches.append(
                {
                    "type": kind,
                    "id": asset.get("id"),
                    "name": asset.get("name") or asset.get("title"),
                    "description": asset.get("description") or asset.get("summary"),
                }
            )
        if len(matches) >= max(1, limit):
            break
    return matches


def asset_get(asset_id: str) -> dict[str, Any]:
    """Fetch one local asset by id (Gene or Capsule)."""
    for _kind, asset in _local_assets():
        if str(asset.get("id")) == asset_id:
            return dict(asset)
    raise LookupError(f"asset not found locally: {asset_id}")


def episode_inspect(
    episode_id: str,
    question: str,
    views: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read a line window of the lossless scene behind one episode.

    ``question`` is required and is recorded only as a host clue in the
    reply. The call does not write the episode, the library, or any pointer;
    a successful call appends one row to the inspect side log.
    """
    import contextlib

    from evolver.gep import episode_record

    result = episode_record.inspect_episode_scene(episode_id, question=question, views=views)
    with contextlib.suppress(Exception):  # the side log must never fail the read
        episode_record.note_inspect_call(result)
    return result


def episode_get(episode_id: str) -> dict[str, Any]:
    """Fetch one episode record by id (read-only).

    经验即证据 §5.1c: the thin read side of the episode store — the same
    read discipline as ``asset_get``, over the runtime-held round record.
    """
    from evolver.gep import episode_record

    body = episode_record.load_episode(episode_id)
    if body is None:
        raise LookupError(f"episode not found: {episode_id}")
    return body


# ---------------------------------------------------------------------------
# Mailbox (durable agent↔daemon messages)
# ---------------------------------------------------------------------------


def mailbox_send(
    type: str,
    payload: dict[str, Any],
    priority: str = "normal",
) -> dict[str, Any]:
    """Enqueue an outbound mailbox message."""
    if priority not in ("high", "normal", "low"):
        raise ValueError(f"priority must be high|normal|low, got {priority}")
    return _mailbox_store().send(type=type, payload=payload, priority=priority)  # type: ignore[arg-type]


def mailbox_poll(limit: int = 10, direction: str = "inbound") -> list[dict[str, Any]]:
    """Poll mailbox messages (newest first).

    ``direction="inbound"`` reads daemon→agent messages; ``"outbound"``
    lists this side's pending sends (useful when no daemon is pumping).
    """
    store = _mailbox_store()
    if direction == "outbound":
        return [m.to_dict() for m in store.poll_outbound(limit=max(1, limit))]
    if direction != "inbound":
        raise ValueError(f"direction must be inbound|outbound, got {direction}")
    return [m.to_dict() for m in store.poll(limit=max(1, limit))]


def mailbox_ack(message_ids: list[str]) -> int:
    """Acknowledge processed messages; returns the acked count."""
    return _mailbox_store().ack(message_ids)


# ---------------------------------------------------------------------------
# Event projections (Sprint 24.1)
# ---------------------------------------------------------------------------


def rebuild_views() -> dict[str, Any]:
    """Replay the event log into derived projections and summarize."""
    views = rebuild_projections_safe()
    return {
        "event_count": views["event_count"],
        "genes": len(views["gene_outcomes"]),
        "cycles": len(views["cycle_timeline"]),
        "path": str(views.get("_path") or ""),
    }


def cycle_timeline(limit: int = 20) -> list[dict[str, Any]]:
    """Recent per-run cycle timelines (stage ladder + the same settlement).

    ``stage`` and ``outcome_status`` come from the last terminal event.
    success settles as ``solidified``; any other non-abort settlement
    settles as ``failed``; ``cycle_abort`` settles as ``aborted``.
    ``outcome_matches_stage`` is true when those two fields agree.
    """
    from evolver.gep.asset_store import read_all_events
    from evolver.gep.event_projection import project_events

    timeline = project_events(read_all_events())["cycle_timeline"]
    result: list[dict[str, Any]] = list(timeline)[-max(1, limit) :]
    return result


def rebuild_projections_safe() -> dict[str, Any]:
    from evolver.gep.event_projection import projections_path, rebuild_projections

    views = rebuild_projections()
    views["_path"] = projections_path()
    return views


_EMPTY_ASSET_SEARCH_HINT: Final[str] = (
    "No local Genes or Capsules matched. Try fewer keywords, or tool_asset_get "
    "when you already have an id."
)
_EMPTY_MAILBOX_HINT: Final[str] = (
    "No mailbox messages in this direction. An empty poll is normal, not a tool failure."
)
_EMPTY_TIMELINE_HINT: Final[str] = (
    "No evolution cycles recorded yet. swarm_tick writes events; "
    "call tool_cycle_timeline again after a cycle."
)
_TIMELINE_SEMANTICS: Final[str] = (
    "stage and outcome_status come from the last terminal event. "
    "success settles as solidified; other non-abort settlements settle as failed; "
    "cycle_abort settles as aborted. An earlier soft_failed does not leave "
    "stage=failed once a later success is recorded."
)
_CORE_LOOP_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "swarm_boot",
        "swarm_tick",
        "swarm_distill",
        "swarm_hypothesis",
        "swarm_propose",
        "swarm_solidify",
        "swarm_feedback",
        "swarm_report",
    }
)


def tool_failure_envelope(tool: str, exc: BaseException) -> dict[str, Any]:
    """Structured failure for a tool the SDK would otherwise stringify.

    Soft-accept paths that already return ``{ok: false, ...}`` do not come
    through here. Raised errors (missing episode, bad enum, bad priority)
    do. ``message`` keeps the underlying text; ``next_steps`` is the action.
    """
    cause = exc.__cause__ or exc
    text = str(exc)
    prefix = f"Error executing tool {tool}: "
    detail = text[len(prefix) :] if text.startswith(prefix) else text
    message = str(cause).strip() or detail
    lowered = message.lower()
    if isinstance(cause, LookupError) or "not found" in lowered:
        error = "not_found"
        steps = [
            f"The id passed to `{tool}` is not in this workspace.",
            "List existing ids (episode list, tool_asset_search, or "
            "tool_cycle_timeline) and call the tool again.",
        ]
    elif isinstance(cause, ValueError) or "validation error" in lowered:
        error = "invalid_arguments"
        steps = [
            f"Read message and fix the arguments for `{tool}` so they match the tool schema.",
            "Call the tool again. This does not stop the swarm loop.",
        ]
    else:
        error = "tool_error"
        steps = [
            f"Read message for `{tool}` and correct the call.",
            "Call swarm_status if the workspace binding looks wrong, then retry once.",
        ]
    return {
        "ok": False,
        "error": error,
        "message": message,
        "tool": tool,
        "next_steps": steps,
    }


def list_envelope(items: list[dict[str, Any]], *, empty_hint: str) -> dict[str, Any]:
    """Object payload for list/search tools. Empty matches stay a dict, never ``[]``.

    Hosts that only read ``content[]`` drop a bare empty list (the body is blank).
    ``ok`` / ``items`` / ``hint`` are present for both empty and non-empty results.
    """
    count = len(items)
    hint = empty_hint if count == 0 else f"{count} item(s)."
    return {"ok": True, "items": items, "hint": hint}


def standing_instructions() -> str:
    """Takeover the host sees on connect. The full protocol is ``swarm_boot``.

    One imperative, not a tool map. ``EVOLVER_SWARM_AUTO_HIJACK`` does not
    change this text. The user's current message still wins. Keep under ~1200
    chars (host hard limit); longer Grok Bot / path detail lives in README.
    """
    return (
        "EVOLVER SWARM is connected. If THIS message already asks for something "
        "else, do that and do not start the loop.\n"
        "If it does not, call swarm_boot and follow its instrument_prompt, "
        "including boot_once. Then one sentence on the actual state: soft-continue "
        "(severity=soft), hard gate, or paused. Say 停 to stop.\n"
        "\n"
        "Loop per turn via next_action:\n"
        "  swarm_tick → edit dispatch_prompt → swarm_distill →\n"
        "  swarm_hypothesis → swarm_solidify → swarm_feedback (score or 0)\n"
        "PROPOSAL REQUIRED or proposal_required=true: swarm_propose that edit, "
        "no free edit.\n"
        "Soft gaps (no_baseline/pack_absent/unmeasured): severity=soft; continue.\n"
        "Grok Bot: /workspace root; src=/workspace/evolver-research/evolver.py; "
        "restart evolver mcp after pull.\n"
        "\n"
        "Stop and never retry on next_action=stop_and_report, await_human, "
        "await_human_approval, await_supervisor_resume, paused=true, "
        "preflight_aborted=true, error=instance_lock_held. "
        "await_human_approval: swarm_approvals, then swarm_approval_resolve "
        "after user decides. "
        "failure_mode.retryable=true: back to swarm_tick. "
        "停: swarm_supervise action pause, then stop. "
        "继续: action resume, then swarm_boot again.\n"
        "Never edit .evolver/ by hand, never solve val here, never call skip_validation."
    )


def build_server() -> Any:
    """Construct the MCP server instance (stdio transport via ``run``)."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.context import Context
    from mcp.shared.exceptions import MCPError
    from mcp_types import CallToolResult, TextContent

    class _HostFacingServer(MCPServer):
        """Same tools, but raised failures are a structured envelope."""

        async def _handle_call_tool(self, ctx: Any, params: Any) -> Any:
            context = Context(
                request_context=ctx,
                mcp_server=self,
                input_params=params,
                subscriptions=self._subscriptions,
            )
            try:
                return await self.call_tool(params.name, params.arguments or {}, context)
            except MCPError:
                raise
            except Exception as exc:
                envelope = tool_failure_envelope(str(getattr(params, "name", "") or ""), exc)
                return CallToolResult(
                    content=[
                        TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))
                    ],
                    structured_content=envelope,
                    is_error=True,
                )

    server: Any = _HostFacingServer("evolver", instructions=standing_instructions())

    # Typed defs first, registered via decorator *expressions* — keeps mypy
    # strict clean (the mcp package ships no stubs, so @server.tool() is Any).
    def tool_asset_search(query: str, limit: int = 10) -> dict[str, Any]:
        """Read-only auxiliary. Search local GEP assets (Genes/Capsules) by keyword."""
        return list_envelope(asset_search(query, limit), empty_hint=_EMPTY_ASSET_SEARCH_HINT)

    def tool_asset_get(asset_id: str) -> dict[str, Any]:
        """Read-only auxiliary. Fetch one local Gene/Capsule by id."""
        return asset_get(asset_id)

    def tool_mailbox_send(
        type: str, payload: dict[str, Any], priority: str = "normal"
    ) -> dict[str, Any]:
        """Auxiliary. Send a durable mailbox message to the evolver daemon."""
        return mailbox_send(type, payload, priority)

    def tool_mailbox_poll(limit: int = 10, direction: str = "inbound") -> dict[str, Any]:
        """Read-only auxiliary. Poll mailbox messages (direction: inbound|outbound)."""
        return list_envelope(mailbox_poll(limit, direction), empty_hint=_EMPTY_MAILBOX_HINT)

    def tool_mailbox_ack(message_ids: list[str]) -> int:
        """Auxiliary. Acknowledge processed mailbox messages."""
        return mailbox_ack(message_ids)

    def tool_rebuild_views() -> dict[str, Any]:
        """Auxiliary. Rebuild event-log projections (gene tallies, cycle timelines)."""
        return rebuild_views()

    def tool_cycle_timeline(limit: int = 20) -> dict[str, Any]:
        """Read-only auxiliary. Recent cycle timelines from the event log.

        stage and outcome_status describe one settlement: the last terminal
        event. success settles as solidified; any other non-abort settlement
        settles as failed; cycle_abort settles as aborted.
        outcome_matches_stage is true when the two fields agree. A non-empty
        result also includes semantics.
        """
        items = cycle_timeline(limit)
        payload = list_envelope(items, empty_hint=_EMPTY_TIMELINE_HINT)
        if items:
            payload["semantics"] = _TIMELINE_SEMANTICS
        return payload

    # Swarm takeover surface (evolver.swarm; clean names, not tool_* — these
    # are the names host agents see and must match the instrument prompt).
    def tool_swarm_boot(
        agent_name: str = "host-agent",
        project: str | None = None,
    ) -> dict[str, Any]:
        """Core loop. Take over this host as an evolver swarm worker (returns the protocol).

        project binds only an existing directory. bound_paths states repo_root
        (code root) and workspace_root. A difference, or a label that is not a
        directory, is a soft warning; the loop still continues.
        """
        from evolver.swarm import swarm_boot

        return swarm_boot(agent_name, project=project)

    async def tool_swarm_tick(
        agent_name: str | None = None,
        include_prompt: bool = True,
        prompt_mode: Literal["full", "short"] = "full",
        checklist_only: bool = False,
    ) -> dict[str, Any]:
        """Core loop. Run one evolution cycle; returns the GEP prompt to execute.

        prompt_mode=full (default) inlines the gene preview. prompt_mode=short
        or checklist_only=true returns the core-loop checklist instead; the
        full prompt is at dispatch_prompt_artifact and evolver://dispatch/last.
        """
        from evolver.swarm import swarm_tick

        return await swarm_tick(
            agent_name=agent_name,
            include_prompt=include_prompt,
            prompt_mode=prompt_mode,
            checklist_only=checklist_only,
        )

    def tool_swarm_distill(response_text: str, dry_run: bool = False) -> dict[str, Any]:
        """Core loop. Distill executed work output into Gene/Capsule candidates."""
        from evolver.swarm import swarm_distill

        return swarm_distill(response_text, dry_run=dry_run)

    def tool_swarm_hypothesis(
        hypothesis: dict[str, Any], agent_name: str = "host-agent"
    ) -> dict[str, Any]:
        """Core loop. Declare this Candidate's one primary hypothesis (演进方案.md §5.3).

        Fields: hypothesis (what you claim), dimension (content|tool|schema),
        mechanism_family, target_hook, mechanism_check (train task refs only —
        the validation reserve is sealed). Optional expected_outcome
        ({"expected_checks_to_pass": [...]}) lets the engine record a
        prediction_delta at settlement. The host owns the claim; the engine
        never invents one. Declaring is not passing: the gate re-reads it.
        """
        from evolver.swarm import swarm_hypothesis

        return swarm_hypothesis(hypothesis=hypothesis, agent_name=agent_name)

    def tool_swarm_propose(
        proposal: dict[str, Any],
        agent_name: str = "host-agent",
        hypothesis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Core loop. S29 mechanical mutation: validate-all-first, exact unique anchor matching.

        hypothesis (§5.3) is recorded before the proposal is applied.
        """
        from evolver.swarm import swarm_propose

        return swarm_propose(proposal=proposal, agent_name=agent_name, hypothesis=hypothesis)

    def tool_swarm_solidify(
        skip_validation: bool = False,
        agent_name: str = "host-agent",
        proposal: dict[str, Any] | None = None,
        hypothesis: dict[str, Any] | None = None,
        validation_scope: str | None = None,
        related_commands: list[list[str]] | None = None,
        restore_stash: bool = False,
    ) -> dict[str, Any]:
        """Core loop. Run the solidify gate: validations, acceptance gate, commit/rollback.

        skip_validation=True is high-risk: it passes the HITL approval gate
        (blocked → await_human_approval; timeout fails safe to reject).
        Optionally accepts a proposal to mechanically apply before validation (S29).
        hypothesis (§5.3) is recorded before gating; no claim, no measurement.
        validation_scope: 'related' | 'cascade' | 'skip'; restore_stash=True restores stash.
        """
        from evolver.swarm import swarm_solidify

        return swarm_solidify(
            skip_validation=skip_validation,
            agent_name=agent_name,
            proposal=proposal,
            hypothesis=hypothesis,
            validation_scope=validation_scope,
            related_commands=related_commands,
            restore_stash=restore_stash,
        )

    def tool_swarm_approvals() -> dict[str, Any]:
        """Read-only. List pending HITL approval requests awaiting a human decision."""
        from evolver.gep.hitl import list_pending, list_recent

        return {"pending": list_pending(), "recent": list_recent(limit=10)}

    def tool_swarm_approval_resolve(
        request_id: str, approve: bool, note: str = ""
    ) -> dict[str, Any]:
        """Swarm control. Relay a HUMAN decision on a pending HITL request (ask the user first)."""
        from evolver.gep.hitl import resolve_approval
        from evolver.swarm import host_relay_blocked

        if approve and host_relay_blocked():
            return {
                "ok": False,
                "error": "host_relay_blocked",
                "hint": "EVOLVER_SWARM_AUTO_HIJACK=1: approve via `evolver hitl approve`",
            }
        return resolve_approval(request_id, approve=approve, decided_by="human-via-host", note=note)

    def tool_swarm_report(
        category: str | None = None,
        description: str | None = None,
        resolution: str | None = None,
        no_write: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Core loop. Heartbeat: capture friction/lessons into the living memory.

        no_write and dry_run are the same switch. Either one persists nothing
        (no rules, no lessons, no report file) and returns wrote=false.
        The default writes and returns wrote=true plus written.
        """
        from evolver.swarm import swarm_report

        return swarm_report(
            category=category,
            description=description,
            resolution=resolution,
            no_write=no_write,
            dry_run=dry_run,
        )

    def tool_swarm_status() -> dict[str, Any]:
        """Read-only. Lightweight engine status for swarm agents (no cycle side effects)."""
        from evolver.swarm import swarm_status

        return swarm_status()

    def tool_swarm_doctor() -> dict[str, Any]:
        """Read-only. Open-box summary (same checks as evolver doctor, never --fix)."""
        from evolver.swarm import swarm_doctor

        return swarm_doctor()

    def tool_swarm_supervise(
        action: Literal["status", "pause", "resume", "direct", "veto", "unveto"],
        text: str | None = None,
        pattern: str | None = None,
        veto_id: str | None = None,
        reason: str = "",
        by: str = "human-via-host",
    ) -> dict[str, Any]:
        """Swarm control. HOTL supervision (relay a HUMAN decision — ask the user first).

        pause/resume the loop, veto a substring pattern, or inject a steering
        directive. tick refuses cycles while paused; vetoed genes have their
        dispatch prompt withheld.
        """
        from evolver.swarm import host_relay_blocked, swarm_supervise

        if action in ("resume", "unveto") and host_relay_blocked():
            return {
                "ok": False,
                "error": "host_relay_blocked",
                "hint": "EVOLVER_SWARM_AUTO_HIJACK=1: resume/unveto via `evolver supervise`",
            }
        return swarm_supervise(
            action,
            text=text,
            pattern=pattern,
            veto_id=veto_id,
            reason=reason,
            by=by,
        )

    def tool_swarm_hooks(
        action: Literal["status", "install", "uninstall"] = "status",
        platform: str = "auto",
        project_dir: str | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Swarm control. Manage IDE/agent file hooks (cursor/claude-code/codex/kiro/opencode...).

        action=status previews what setup-hooks would write for the platform.
        """
        from evolver.swarm import swarm_hooks

        return swarm_hooks(
            action=action,
            platform=platform,
            project_dir=project_dir,
            force=force,
            dry_run=dry_run,
        )

    def tool_swarm_checkpoint_working(content: str) -> dict[str, Any]:
        """Swarm control. Write WORKING_SESSION.md and clear a pending compaction checkpoint."""
        from evolver.swarm import swarm_checkpoint_working

        return swarm_checkpoint_working(content)

    def tool_swarm_hook_event(
        event: Literal["session_start", "session_end", "signal_detect", "precompact"],
        payload: dict[str, Any] | None = None,
        source: str = "host-agent",
    ) -> dict[str, Any]:
        """Swarm control. In-process hook bridge (for hosts without file hooks).

        Call at session boundaries and when error output is observed; the
        payload's `content` text is scanned and detected signals are injected
        into the next cycle's selection.
        """
        from evolver.swarm import swarm_hook_event

        return swarm_hook_event(event, payload=payload, source=source)

    def tool_swarm_feedback(
        primary_score: float,
        textual_gradient: str = "",
        metrics: dict[str, float] | None = None,
        success: bool = True,
        error_message: str | None = None,
        eval_mode: Literal["train", "validation", "test"] = "validation",
        sample_count: int = 0,
        agent_name: str = "host-agent",
        run_id: str | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        """Core loop. Report unified evaluation feedback E (score/metrics/gradient)."""
        from evolver.swarm import swarm_feedback

        return swarm_feedback(
            primary_score=primary_score,
            textual_gradient=textual_gradient,
            metrics=metrics,
            success=success,
            error_message=error_message,
            eval_mode=eval_mode,
            sample_count=sample_count,
            agent_name=agent_name,
            run_id=run_id,
            cycle_id=cycle_id,
        )

    def tool_swarm_skills(
        action: Literal["scan", "list", "sync"],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Swarm control. Skill ecosystem bridge: scan host skill roots (project > user >
        builtin), list synced skill genes, or sync skills into the store."""
        from evolver.swarm import swarm_skills

        return swarm_skills(action=action, dry_run=dry_run)

    def tool_swarm_workflow_run(
        file: str | None = None,
        template: str | None = None,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """Swarm control. Start a durable evolution workflow from a YAML/JSON spec file or a
        bundled template (repair-cycle / innovate-cycle). Returns the state,
        including the agent role + instruction the host should execute now."""
        from evolver.swarm import swarm_workflow_run

        return swarm_workflow_run(file=file, template=template, workflow_id=workflow_id)

    def tool_swarm_workflow_act(
        workflow_id: str,
        action: Literal["approve", "reject", "complete", "resume", "cancel"],
        result: Any = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Swarm control. Advance a waiting workflow: approve/reject its approval gate,
        complete its agent step with the host's result, resume, or cancel."""
        from evolver.swarm import swarm_workflow_act

        return swarm_workflow_act(workflow_id=workflow_id, action=action, result=result, note=note)

    def tool_swarm_workflow_status(workflow_id: str) -> dict[str, Any]:
        """Read-only. Full state of one workflow run — step index, variables, gate
        verdicts, and what the host executor should do next."""
        from evolver.swarm import swarm_workflow_status

        return swarm_workflow_status(workflow_id=workflow_id)

    def prompt_evolver_swarm(agent_name: str = "host-agent") -> str:
        """Instrument prompt: inject the swarm-evolution takeover protocol."""
        from evolver.swarm import swarm_boot

        return str(swarm_boot(agent_name)["instrument_prompt"])

    # Resources (read-only state surfaces — hosts can subscribe/read these
    # without tool round-trips; dicts are auto-serialized to JSON).
    def resource_status() -> dict[str, Any]:
        from evolver.swarm import swarm_status

        return swarm_status()

    def resource_instrument_prompt() -> str:
        from evolver.swarm import build_instrument_prompt, swarm_status

        return build_instrument_prompt({**swarm_status(), "agent_name": "resource-reader"})

    def resource_dispatch_last() -> str:
        from evolver.gep.paths import get_evolution_dir

        artifact = get_evolution_dir() / "last_prompt.md"
        if artifact.exists():
            return artifact.read_text(encoding="utf-8")
        return "(no dispatch prompt artifact yet)"

    def resource_events_recent() -> list[dict[str, Any]]:
        return cycle_timeline(10)

    server.resource(
        "evolver://status", name="status", description="Live swarm/engine status (JSON)"
    )(resource_status)
    server.resource(
        "evolver://instrument-prompt",
        name="instrument-prompt",
        description="The swarm takeover instrument prompt (current render)",
    )(resource_instrument_prompt)
    server.resource(
        "evolver://dispatch/last",
        name="dispatch-last",
        description="Last GEP dispatch prompt artifact (last_prompt.md)",
    )(resource_dispatch_last)
    server.resource(
        "evolver://events/recent",
        name="events-recent",
        description="Recent evolution cycle timeline (JSON)",
    )(resource_events_recent)

    # Tool annotations (MCP spec hints: hosts may surface confirmations or
    # skip read-only tools in plan mode).
    from mcp.types import ToolAnnotations

    read_only = ToolAnnotations(read_only_hint=True)
    destructive = ToolAnnotations(destructive_hint=True)

    classic_tools: list[tuple[str, ToolAnnotations | None]] = [
        ("tool_asset_search", read_only),
        ("tool_asset_get", read_only),
        ("episode_get", read_only),
        ("episode_inspect", read_only),
        ("tool_mailbox_send", None),
        ("tool_mailbox_poll", read_only),
        ("tool_mailbox_ack", None),
        ("tool_rebuild_views", None),
        ("tool_cycle_timeline", read_only),
    ]
    classic_fns = {
        "tool_asset_search": tool_asset_search,
        "tool_asset_get": tool_asset_get,
        "episode_get": episode_get,
        "episode_inspect": episode_inspect,
        "tool_mailbox_send": tool_mailbox_send,
        "tool_mailbox_poll": tool_mailbox_poll,
        "tool_mailbox_ack": tool_mailbox_ack,
        "tool_rebuild_views": tool_rebuild_views,
        "tool_cycle_timeline": tool_cycle_timeline,
    }
    for name, ann in classic_tools:
        fn = classic_fns[name]
        read_only_hint = bool(ann is not None and ann.read_only_hint)
        if name.startswith("episode_"):
            role = "Read-only record"
        elif read_only_hint:
            role = "Read-only auxiliary"
        else:
            role = "Auxiliary"
        server.tool(name=name, title=f"{role}: {name}", annotations=ann)(fn)

    # Schema titles follow the function __name__. The wrappers below are
    # named tool_swarm_* in source; align that to the public swarm_* name
    # so hosts do not see tool_swarm_tickArguments for a tool called swarm_tick.

    swarm_tools: list[tuple[str, Callable[..., Any], ToolAnnotations | None]] = [
        ("swarm_boot", tool_swarm_boot, None),
        ("swarm_tick", tool_swarm_tick, None),
        ("swarm_distill", tool_swarm_distill, None),
        ("swarm_hypothesis", tool_swarm_hypothesis, destructive),
        ("swarm_propose", tool_swarm_propose, destructive),
        ("swarm_solidify", tool_swarm_solidify, destructive),
        ("swarm_feedback", tool_swarm_feedback, None),
        ("swarm_report", tool_swarm_report, None),
        ("swarm_status", tool_swarm_status, read_only),
        ("swarm_doctor", tool_swarm_doctor, read_only),
        ("swarm_approvals", tool_swarm_approvals, read_only),
        ("swarm_approval_resolve", tool_swarm_approval_resolve, destructive),
        ("swarm_supervise", tool_swarm_supervise, destructive),
        ("swarm_hooks", tool_swarm_hooks, None),
        ("swarm_hook_event", tool_swarm_hook_event, None),
        ("swarm_checkpoint_working", tool_swarm_checkpoint_working, None),
        ("swarm_skills", tool_swarm_skills, None),
        ("swarm_workflow_run", tool_swarm_workflow_run, None),
        ("swarm_workflow_act", tool_swarm_workflow_act, destructive),
        ("swarm_workflow_status", tool_swarm_workflow_status, read_only),
    ]
    for name, fn, ann in swarm_tools:
        fn.__name__ = name
        read_only_hint = bool(ann is not None and ann.read_only_hint)
        if name in _CORE_LOOP_TOOLS:
            role = "Core loop"
        elif read_only_hint:
            role = "Read-only"
        else:
            role = "Swarm"
        server.tool(name=name, title=f"{role}: {name}", annotations=ann)(fn)

    server.prompt(name="evolver_swarm", title="Evolver Swarm Takeover")(prompt_evolver_swarm)

    return server


def main(project: str | None = None) -> int:
    """Entry point for ``evolver mcp`` — stdio transport."""
    import contextlib
    import os

    from evolver.gep.paths import ensure_workspace_meta, get_repo_root
    from evolver.ops.soak_env import maybe_route_to_soak

    if project and str(project).strip():
        import sys

        from evolver.swarm import bind_project_directory

        info = bind_project_directory(project)
        if not info.get("project_applied"):
            print(
                f"[mcp] project {info.get('project')!r} is not an existing directory; "
                "workspace was not rebound",
                file=sys.stderr,
            )
    else:
        found = get_repo_root(_quiet=True)
        if found is not None and not os.environ.get("EVOLVER_REPO_ROOT"):
            os.environ["EVOLVER_REPO_ROOT"] = str(found)
    with contextlib.suppress(Exception):
        ensure_workspace_meta()
    maybe_route_to_soak()
    build_server().run(transport="stdio")
    return 0


if __name__ == "__main__":  # `python -m evolver.mcp_server` (host configs)
    raise SystemExit(main())


__all__ = [
    "asset_get",
    "asset_search",
    "build_server",
    "cycle_timeline",
    "episode_get",
    "episode_inspect",
    "mailbox_ack",
    "mailbox_poll",
    "mailbox_send",
    "main",
    "rebuild_views",
]
