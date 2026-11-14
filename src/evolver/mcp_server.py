"""MCP server — FSM dynamic 3-tool atomic surface (算子即基因 P1-1).

Exposes a zero-cognitive-load finite-state tool catalog over stdio MCP:

- ``IDLE`` state:
  - ``evolve_begin`` (start a round & lock one plain-string hypothesis)
  - ``evolve_status`` (read-only status & signal discovery)
- ``ACTIVE_RUN`` state:
  - ``run_lens`` (read-only AST / impact / traceback / contract diagnostics)
  - ``evolve_settle`` (``< 3s`` L0 lightning validation, blackbox + episode
    settlement, dual-track draft preservation vs. vault promotion)
  - ``evolve_status`` (read-only status)

Read-only record & asset lookup helpers (``episode_get``, ``episode_inspect``,
``tool_asset_search``, ``tool_asset_get``, ``tool_cycle_timeline``) remain
available as non-mutating auxiliaries. Whenever ``fsm_state()`` transitions
between ``IDLE`` and ``ACTIVE_RUN``, the server automatically pushes
``notifications/tools/list_changed`` so MCP hosts refresh their tool catalog
immediately.
"""

from __future__ import annotations

import contextlib
import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field

from evolver.proxy.mailbox.store import MailboxStore


def _mailbox_dir() -> Path:
    from evolver.gep.paths import get_mailbox_dir

    return get_mailbox_dir()


def _mailbox_store() -> MailboxStore:
    return MailboxStore(_mailbox_dir())


# ---------------------------------------------------------------------------
# Assets & Episodes (local-first, read-only)
# ---------------------------------------------------------------------------


def _local_assets() -> list[tuple[str, dict[str, Any]]]:
    from evolver.gep.asset_store import load_capsules, load_genes

    return [
        *[("gene", g) for g in load_genes()],
        *[("capsule", c) for c in load_capsules()],
    ]


def asset_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search local Genes/Capsules by token-AND over id/name/summary/signals."""
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
    """Read a val-sealed line window of the lossless scene behind one episode."""
    from evolver.gep import episode_record

    result = episode_record.inspect_episode_scene(episode_id, question=question, views=views)
    with contextlib.suppress(Exception):
        episode_record.note_inspect_call(result)
    return result


def episode_get(episode_id: str) -> dict[str, Any]:
    """Fetch one episode record by id (read-only)."""
    from evolver.gep import episode_record

    body = episode_record.load_episode(episode_id)
    if body is None:
        raise LookupError(f"episode not found: {episode_id}")
    return body


# ---------------------------------------------------------------------------
# Mailbox & Projections (Python API preserved for internal callers)
# ---------------------------------------------------------------------------


def mailbox_send(
    type: str,
    payload: dict[str, Any],
    priority: str = "normal",
) -> dict[str, Any]:
    if priority not in ("high", "normal", "low"):
        raise ValueError(f"priority must be high|normal|low, got {priority}")
    return _mailbox_store().send(type=type, payload=payload, priority=priority)  # type: ignore[arg-type]


def mailbox_poll(limit: int = 10, direction: str = "inbound") -> list[dict[str, Any]]:
    store = _mailbox_store()
    if direction == "outbound":
        return [m.to_dict() for m in store.poll_outbound(limit=max(1, limit))]
    if direction != "inbound":
        raise ValueError(f"direction must be inbound|outbound, got {direction}")
    return [m.to_dict() for m in store.poll(limit=max(1, limit))]


def mailbox_ack(message_ids: list[str]) -> int:
    return _mailbox_store().ack(message_ids)


def rebuild_projections_safe() -> dict[str, Any]:
    from evolver.gep.event_projection import projections_path, rebuild_projections

    views = rebuild_projections()
    views["_path"] = projections_path()
    return views


def rebuild_views() -> dict[str, Any]:
    views = rebuild_projections_safe()
    return {
        "event_count": views["event_count"],
        "genes": len(views["gene_outcomes"]),
        "cycles": len(views["cycle_timeline"]),
        "path": str(views.get("_path") or ""),
    }


def cycle_timeline(limit: int = 20) -> list[dict[str, Any]]:
    from evolver.gep.asset_store import read_all_events
    from evolver.gep.event_projection import project_events

    timeline = project_events(read_all_events())["cycle_timeline"]
    return list(timeline)[-max(1, limit) :]


_EMPTY_ASSET_SEARCH_HINT: Final[str] = (
    "No local Genes or Capsules matched. Try fewer keywords, or tool_asset_get "
    "when you already have an id."
)
_EMPTY_TIMELINE_HINT: Final[str] = (
    "No evolution cycles recorded yet. Complete an evolve_begin -> evolve_settle "
    "round and query tool_cycle_timeline again."
)
_TIMELINE_SEMANTICS: Final[str] = (
    "stage and outcome_status come from the last terminal event. "
    "success settles as solidified; other non-abort settlements settle as failed."
)

#: FSM visibility rules for ``tools/list`` and hard call gating.
IDLE_ONLY_TOOLS: Final[frozenset[str]] = frozenset({"evolve_begin"})
ACTIVE_ONLY_TOOLS: Final[frozenset[str]] = frozenset({"run_lens", "evolve_settle"})


def visible_tools_for_state(state: str, all_names: list[str]) -> list[str]:
    """Filter registered tool names according to FSM state (``IDLE`` vs ``ACTIVE_RUN``)."""
    hidden = ACTIVE_ONLY_TOOLS if state == "IDLE" else IDLE_ONLY_TOOLS
    return [n for n in all_names if n not in hidden]


def tool_failure_envelope(tool: str, exc: BaseException) -> dict[str, Any]:
    """Structured failure envelope for raised tool exceptions."""
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
            "List existing ids via tool_asset_search or tool_cycle_timeline and retry.",
        ]
    elif isinstance(cause, ValueError) or "validation error" in lowered:
        error = "invalid_arguments"
        steps = [
            f"Read message and fix the arguments for `{tool}` so they match the tool schema.",
            "Call the tool again.",
        ]
    else:
        error = "tool_error"
        steps = [
            f"Read message for `{tool}` and correct the call.",
            "Call evolve_status to verify workspace state and current FSM phase.",
        ]
    return {
        "ok": False,
        "error": error,
        "message": message,
        "tool": tool,
        "next_steps": steps,
    }


def _fsm_mismatch_envelope(tool: str, current_state: str) -> dict[str, Any]:
    allowed = (
        ["evolve_begin", "evolve_status"]
        if current_state == "IDLE"
        else ["run_lens", "evolve_settle", "evolve_status"]
    )
    next_act = "evolve_begin" if current_state == "IDLE" else "evolve_settle"
    return {
        "ok": False,
        "error": "fsm_state_mismatch",
        "tool": tool,
        "fsm_state": current_state,
        "allowed_tools": allowed,
        "next_action": next_act,
        "message": (
            f"Tool `{tool}` is unavailable in FSM state `{current_state}`. "
            f"Allowed core tools now: {', '.join(allowed)}."
        ),
        "next_steps": [
            f"Refresh your tool list or call `{next_act}` directly.",
        ],
    }


def _host_tool_description(fn: Callable[..., Any]) -> str:
    return inspect.cleandoc(fn.__doc__ or "")


def list_envelope(items: list[dict[str, Any]], *, empty_hint: str) -> dict[str, Any]:
    count = len(items)
    hint = empty_hint if count == 0 else f"{count} item(s)."
    return {"ok": True, "items": items, "hint": hint}


def standing_instructions() -> str:
    """Concise server takeover instructions (< 600 chars, zero internal flag jargon)."""
    return (
        "EVOLVER SWARM is connected (FSM 3-tool autopilot protocol).\n"
        "If the user's current message asks for another task, do that first.\n"
        "Otherwise run the atomic self-evolution loop:\n"
        '  1. IDLE: call `evolve_begin(hypothesis="one sentence claim")`.\n'
        "  2. ACTIVE_RUN: inspect with `run_lens`, make a focused single-component edit,\n"
        '     then call `evolve_settle(summary="what changed")` (< 3s lightning check).\n'
        "  3. On `ok=false` (`draft_preserved`), your patch stays intact—fix the 3-line\n"
        "     `actionable_fix` and run `evolve_begin` again. Never edit `~/.evolver/`."
    )


def _enable_tool_catalog_refresh(server: Any) -> None:
    """Advertise ``tools.listChanged=True`` and emit ``notifications/tools/list_changed``."""
    low = server._lowlevel_server
    original = low.create_initialization_options

    def create_initialization_options(*args: Any, **kwargs: Any) -> Any:
        from mcp.server.lowlevel.server import NotificationOptions

        if not args and kwargs.get("notification_options") is None:
            kwargs["notification_options"] = NotificationOptions(
                prompts_changed=True,
                resources_changed=True,
                tools_changed=True,
            )
        return original(*args, **kwargs)

    low.create_initialization_options = create_initialization_options

    async def _on_initialized(ctx: Any, params: Any) -> None:
        _ = params
        await ctx.session.send_tool_list_changed()

    from mcp_types import NotificationParams

    low.add_notification_handler(
        "notifications/initialized",
        NotificationParams,
        _on_initialized,
    )


def build_server(*, lazy_bootstrap: bool = False) -> Any:
    """Construct the FSM-gated MCP server instance."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.context import Context
    from mcp.shared.exceptions import MCPError
    from mcp.types import ToolAnnotations
    from mcp_types import CallToolResult, TextContent

    from evolver.swarm import fsm_state

    class _HostFacingServer(MCPServer):
        """FSM-gated MCP server with dynamic ``list_tools`` and ``list_changed`` pushes."""

        async def list_tools(self) -> list[Any]:
            all_tools = await super().list_tools()
            cur = fsm_state()
            hidden = ACTIVE_ONLY_TOOLS if cur == "IDLE" else IDLE_ONLY_TOOLS
            return [t for t in all_tools if t.name not in hidden]

        async def _handle_call_tool(self, ctx: Any, params: Any) -> Any:
            tool_name = str(getattr(params, "name", "") or "")
            before = fsm_state()

            # Hard FSM guard for stale client tool caches
            if (before == "IDLE" and tool_name in ACTIVE_ONLY_TOOLS) or (
                before == "ACTIVE_RUN" and tool_name in IDLE_ONLY_TOOLS
            ):
                mismatch = _fsm_mismatch_envelope(tool_name, before)
                with contextlib.suppress(Exception):
                    await ctx.session.send_tool_list_changed()
                return CallToolResult(
                    content=[
                        TextContent(type="text", text=json.dumps(mismatch, ensure_ascii=False))
                    ],
                    structured_content=mismatch,
                    is_error=True,
                )

            context = Context(
                request_context=ctx,
                mcp_server=self,
                input_params=params,
                subscriptions=self._subscriptions,
            )
            try:
                res = await self.call_tool(tool_name, params.arguments or {}, context)
            except MCPError:
                raise
            except Exception as exc:
                envelope = tool_failure_envelope(tool_name, exc)
                return CallToolResult(
                    content=[
                        TextContent(type="text", text=json.dumps(envelope, ensure_ascii=False))
                    ],
                    structured_content=envelope,
                    is_error=True,
                )

            after = fsm_state()
            if after != before:
                with contextlib.suppress(Exception):
                    await ctx.session.send_tool_list_changed()
            return res

    server: Any = _HostFacingServer("evolver", instructions=standing_instructions())

    # -----------------------------------------------------------------------
    # Core 3-tool FSM surface + evolve_status
    # -----------------------------------------------------------------------

    async def tool_evolve_begin(
        hypothesis: Annotated[
            str,
            Field(
                description=(
                    "Plain one-sentence hypothesis describing the single bug fix "
                    "or improvement mechanism to validate in this round. Leave empty "
                    "with auto_discover=True to preview top signals & candidate operators first."
                )
            ),
        ] = "",
        target_files: Annotated[
            list[str] | None,
            Field(description="Optional relative file paths you expect to touch."),
        ] = None,
        auto_discover: Annotated[
            bool,
            Field(description="Automatically scan workspace signals and match operator genes."),
        ] = True,
        discard_draft: Annotated[
            bool,
            Field(description="Revert uncommitted tracked draft edits before starting."),
        ] = False,
        project: Annotated[
            str | None,
            Field(description="Optional existing project directory path to bind."),
        ] = None,
        agent_name: str = "host-agent",
    ) -> dict[str, Any]:
        """Core FSM (IDLE -> ACTIVE_RUN). Lock one plain-sentence hypothesis and start a round."""
        from evolver.swarm import evolve_begin

        return await evolve_begin(
            hypothesis=hypothesis,
            target_files=target_files,
            auto_discover=auto_discover,
            discard_draft=discard_draft,
            project=project,
            agent_name=agent_name,
        )

    def tool_run_lens(
        name: Annotated[
            Literal["list", "ast_hotspot", "import_impact", "trace_locator", "contract_surface"]
            | str,
            Field(
                description=(
                    "Lens name (`list`, `ast_hotspot`, `import_impact`, "
                    "`trace_locator`, `contract_surface`, or an operator gene id)."
                )
            ),
        ] = "list",
        target: Annotated[
            str,
            Field(
                description="Relative file/directory path (or traceback text for trace_locator)."
            ),
        ] = ".",
        args: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Optional lens parameters (e.g. {'traceback': '...'} or {'files': [...]})."
                )
            ),
        ] = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        """Core FSM (ACTIVE_RUN, read-only). Run a deterministic Python diagnostic lens."""
        from evolver.swarm import evolve_run_lens

        return evolve_run_lens(name=name, target=target, args=args, project=project)

    def tool_evolve_settle(
        summary: Annotated[
            str,
            Field(description="Concise summary of the change applied during this round."),
        ] = "",
        validation_scope: Annotated[
            Literal["auto", "lightning", "cascade", "related"],
            Field(
                description=(
                    "`auto` (default) runs `< 3s` AST reverse-dependency L0 lightning "
                    "validation and escalates to L2 only on high-risk surfaces."
                )
            ),
        ] = "auto",
        related_commands: Annotated[
            list[list[str]] | None,
            Field(description="Explicit argv list when validation_scope='related'."),
        ] = None,
        restore_draft: Annotated[
            bool,
            Field(description="Restore the last backed-up draft from rejected_stashes."),
        ] = False,
        project: str | None = None,
        agent_name: str = "host-agent",
    ) -> dict[str, Any]:
        """Core FSM (ACTIVE_RUN -> IDLE). Validate, settle blackbox/episode, promote or draft."""
        from evolver.swarm import evolve_settle

        return evolve_settle(
            summary=summary,
            validation_scope=validation_scope,
            related_commands=related_commands,
            restore_draft=restore_draft,
            project=project,
            agent_name=agent_name,
        )

    def tool_evolve_status(project: str | None = None) -> dict[str, Any]:
        """Read-only status. Inspect current FSM state, vault counts, signals, and saved time."""
        from evolver.swarm import evolve_status

        return evolve_status(project=project)

    # -----------------------------------------------------------------------
    # Read-only auxiliary lookup tools
    # -----------------------------------------------------------------------

    def tool_asset_search(query: str, limit: int = 10) -> dict[str, Any]:
        """Read-only auxiliary. Search local GEP assets (Genes/Capsules) by keyword."""
        return list_envelope(asset_search(query, limit), empty_hint=_EMPTY_ASSET_SEARCH_HINT)

    def tool_asset_get(asset_id: str) -> dict[str, Any]:
        """Read-only auxiliary. Fetch one local Gene/Capsule by id."""
        return asset_get(asset_id)

    def tool_cycle_timeline(limit: int = 20) -> dict[str, Any]:
        """Read-only auxiliary. Recent cycle timelines from the event log."""
        items = cycle_timeline(limit)
        payload = list_envelope(items, empty_hint=_EMPTY_TIMELINE_HINT)
        if items:
            payload["semantics"] = _TIMELINE_SEMANTICS
        return payload

    def prompt_evolver_swarm(agent_name: str = "host-agent") -> str:
        """Instrument prompt: inject the concise 3-tool FSM takeover protocol."""
        from evolver.swarm import build_instrument_prompt, evolve_status

        return build_instrument_prompt({**evolve_status(), "agent_name": agent_name})

    # -----------------------------------------------------------------------
    # Resources
    # -----------------------------------------------------------------------

    def resource_status() -> dict[str, Any]:
        from evolver.swarm import evolve_status

        return evolve_status()

    def resource_instrument_prompt() -> str:
        from evolver.swarm import build_instrument_prompt, evolve_status

        return build_instrument_prompt({**evolve_status(), "agent_name": "resource-reader"})

    def resource_dispatch_last() -> str:
        from evolver.gep.paths import get_evolution_dir

        artifact = get_evolution_dir() / "last_prompt.md"
        if artifact.exists():
            return artifact.read_text(encoding="utf-8")
        return "(no dispatch prompt artifact yet)"

    def resource_events_recent() -> list[dict[str, Any]]:
        return cycle_timeline(10)

    server.resource(
        "evolver://status", name="status", description="Live FSM & engine status (JSON)"
    )(resource_status)
    server.resource(
        "evolver://instrument-prompt",
        name="instrument-prompt",
        description="The 3-tool FSM takeover instrument prompt",
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

    read_only = ToolAnnotations(read_only_hint=True)
    destructive = ToolAnnotations(destructive_hint=True)

    _lazy_bootstrapped = False

    def _with_lazy_bootstrap(fn: Callable[..., Any], *, skip: bool = False) -> Callable[..., Any]:
        if not lazy_bootstrap or skip:
            return fn
        import functools

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_wrapped(*args: Any, **kwargs: Any) -> Any:
                nonlocal _lazy_bootstrapped
                if not _lazy_bootstrapped:
                    _lazy_bootstrapped = True
                    with contextlib.suppress(Exception):
                        from evolver.swarm import _maybe_lazy_bootstrap

                        _maybe_lazy_bootstrap()
                return await fn(*args, **kwargs)

            return _async_wrapped

        @functools.wraps(fn)
        def _sync_wrapped(*args: Any, **kwargs: Any) -> Any:
            nonlocal _lazy_bootstrapped
            if not _lazy_bootstrapped:
                _lazy_bootstrapped = True
                with contextlib.suppress(Exception):
                    from evolver.swarm import _maybe_lazy_bootstrap

                    _maybe_lazy_bootstrap()
            return fn(*args, **kwargs)

        return _sync_wrapped

    registrations: list[tuple[str, Callable[..., Any], ToolAnnotations | None, str]] = [
        ("evolve_begin", tool_evolve_begin, None, "Core FSM"),
        ("run_lens", tool_run_lens, read_only, "Core FSM"),
        ("evolve_settle", tool_evolve_settle, destructive, "Core FSM"),
        ("evolve_status", tool_evolve_status, read_only, "Read-only"),
        ("episode_get", episode_get, read_only, "Read-only record"),
        ("episode_inspect", episode_inspect, read_only, "Read-only record"),
        ("tool_asset_search", tool_asset_search, read_only, "Read-only auxiliary"),
        ("tool_asset_get", tool_asset_get, read_only, "Read-only auxiliary"),
        ("tool_cycle_timeline", tool_cycle_timeline, read_only, "Read-only auxiliary"),
    ]

    for name, raw_fn, ann, role in registrations:
        fn = _with_lazy_bootstrap(raw_fn, skip=(name == "evolve_begin"))
        fn.__name__ = name
        server.tool(
            name=name,
            title=f"{role}: {name}",
            description=_host_tool_description(fn),
            annotations=ann,
        )(fn)

    server.prompt(name="evolver_swarm", title="Evolver Swarm Takeover")(prompt_evolver_swarm)
    _enable_tool_catalog_refresh(server)

    return server


def main(project: str | None = None) -> int:
    """Entry point for ``evolver mcp`` — stdio transport."""
    import os
    import sys

    from evolver.gep.paths import ensure_workspace_meta, get_repo_root
    from evolver.ops.soak_env import maybe_route_to_soak

    if project and str(project).strip():
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
    build_server(lazy_bootstrap=True).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACTIVE_ONLY_TOOLS",
    "IDLE_ONLY_TOOLS",
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
    "visible_tools_for_state",
]
