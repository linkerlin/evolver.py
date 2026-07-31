"""Static Hub egress chokepoint coverage (Node hubEgressCoverage)."""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "evolver"

_REVIEWED_CLIENTS = (
    "atp/hub_client.py",
    "atp/client.py",
    "atp/service_helper.py",
    "gep/sync.py",
    "gep/fetch.py",
    "gep/discovery.py",
    "gep/directory_client.py",
    "gep/oauth_login.py",
    "adapters/auth.py",
    "proxy/lifecycle/manager.py",
    "proxy/extensions/skill_updater.py",
    "proxy/extensions/trace_control.py",
    "recipe/client.py",
)

_CHOKKEPOINT_IMPORT_RE = re.compile(
    r"\b("
    r"hub_fetch|hub_get|hub_post|"
    r"enforce_hub_scheme|resolve_hub_url|resolve_hub_base|"
    r"get_hub_url|post_hub_envelope|build_hub_headers|"
    r"from evolver\.gep\.hub_fetch|from evolver\.config import|"
    r"from evolver\.gep\.a2a_protocol|"
    r"from evolver\.atp\.hub_client|hub_client"
    r")\b"
)

_BARE_HTTPX_CLIENT_RE = re.compile(
    r"\bhttpx\.(AsyncClient|Client|request|get|post|put|delete|patch)\b"
)
_NATIVE_SOCKET_RE = re.compile(
    r"\b(urllib\.request|requests\.(get|post)|aiohttp\.ClientSession)\b"
)


def _read(rel: str) -> str:
    path = _SRC / rel
    assert path.is_file(), f"missing reviewed module: {rel}"
    return path.read_text(encoding="utf-8")


def test_hub_fetch_enforces_tls_scheme() -> None:
    src = _read("gep/hub_fetch.py")
    assert "enforce_hub_scheme" in src
    assert re.search(r"def hub_fetch\(", src)
    fetch_body = src[src.index("def hub_fetch") :]
    enforce_pos = fetch_body.find("enforce_hub_scheme")
    request_pos = fetch_body.find("httpx.request")
    assert 0 <= enforce_pos < request_pos


def test_a2a_protocol_post_envelope_enforces_tls() -> None:
    src = _read("gep/a2a_protocol.py")
    assert "enforce_hub_scheme" in src
    assert "def post_hub_envelope" in src
    body = src[src.index("def post_hub_envelope") :]
    next_def = re.search(r"\n(?:async )?def ", body[1:])
    if next_def:
        body = body[: next_def.start() + 1]
    assert "enforce_hub_scheme" in body


def test_config_exports_tls_helpers() -> None:
    src = _read("config.py")
    assert "def enforce_hub_scheme" in src
    assert "def resolve_hub_url" in src
    assert "def resolve_hub_base" in src


def test_reviewed_clients_use_chokepoint() -> None:
    offenders: list[str] = []
    for rel in _REVIEWED_CLIENTS:
        src = _read(rel)
        talks_hub = bool(
            re.search(
                r"\b(A2A_HUB|/a2a/|resolve_hub|get_hub_url|publish_service|"
                r"hub_client|Hub URL|evomap\.ai)\b",
                src,
                re.I,
            )
        )
        if not talks_hub:
            continue
        if not _CHOKKEPOINT_IMPORT_RE.search(src):
            offenders.append(rel)
    assert offenders == [], (
        "reviewed Hub clients must import a chokepoint helper:\n  " + "\n  ".join(offenders)
    )


def test_reviewed_clients_avoid_native_socket_apis() -> None:
    offenders = [rel for rel in _REVIEWED_CLIENTS if _NATIVE_SOCKET_RE.search(_read(rel))]
    assert offenders == [], "must not use urllib/requests/aiohttp: " + ", ".join(offenders)


def test_session_end_has_no_bare_hub_http() -> None:
    src = _read("adapters/scripts/session_end.py")
    if _BARE_HTTPX_CLIENT_RE.search(src) or _NATIVE_SOCKET_RE.search(src):
        assert _CHOKKEPOINT_IMPORT_RE.search(src)


def test_cli_fetch_and_sync_route_via_chokepoint_modules() -> None:
    cli = (_SRC / "cli.py").read_text(encoding="utf-8")
    assert "from evolver.gep.fetch" in cli
    assert "from evolver.gep.sync" in cli
    assert "import httpx" not in cli
    assert "httpx." not in cli


def test_service_helper_delegates_to_hub_client() -> None:
    src = _read("atp/service_helper.py")
    assert "hub_client" in src
    assert "publish_service" in src
    assert not _BARE_HTTPX_CLIENT_RE.search(src)
    assert not _NATIVE_SOCKET_RE.search(src)


def test_hub_fetch_callable_surface() -> None:
    from evolver.gep import hub_fetch as hf  # noqa: PLC0415

    assert callable(hf.hub_fetch)
    assert callable(hf.hub_get)
    assert callable(hf.hub_post)
