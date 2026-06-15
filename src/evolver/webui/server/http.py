"""WebUI HTTP server — unified FastAPI app factory and optional embedded server.

Equivalent to evolver/src/webui/server/http.js plus server.js route wiring.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from uvicorn import Config, Server

from evolver.webui.client import (
    BOOTSTRAP_JS,
    COMMON_JS,
    DARK_THEME_CSS,
    I18N_JS,
    render_index_html,
    render_sse_client_js,
    static_routes,
)
from evolver.webui.dashboard import render_dashboard
from evolver.webui.server.legacy_routes import router as legacy_router
from evolver.webui.server.routes import router as api_router

logger = logging.getLogger(__name__)

DEFAULT_WEBUI_PORT = 8080
MAX_PORT_ATTEMPTS = 50


def create_app(*, title: str = "Evolver WebUI", version: str = "1.8.0") -> FastAPI:
    """Build the single WebUI FastAPI application (dashboard + API + legacy routes)."""
    app = FastAPI(title=title, version=version)
    app.include_router(api_router)
    app.include_router(legacy_router)
    app.include_router(static_routes())

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return render_dashboard()

    @app.get("/classic", response_class=HTMLResponse)
    async def classic_client() -> str:
        """Modular client shell (bootstrap + SSE modules); primary UI is ``/``."""
        return render_index_html(
            overall_status="healthy",
            status_json="{}",
            gene_count=0,
            capsule_count=0,
        )

    @app.get("/app.js", response_class=PlainTextResponse)
    async def app_js() -> str:
        return (
            BOOTSTRAP_JS
            + "\n"
            + COMMON_JS
            + "\n"
            + render_sse_client_js()
            + "\n"
            + I18N_JS
        )

    @app.get("/app.css", response_class=PlainTextResponse)
    async def app_css() -> str:
        return DARK_THEME_CSS

    return app


class WebUiServer:
    """Embedded WebUI server with automatic port fallback."""

    def __init__(self, port: int | None = None) -> None:
        from evolver.config import resolve_webui_port

        self.port = port if port is not None else resolve_webui_port()
        self._app = create_app()
        self._server: Server | None = None
        self.actual_port: int | None = None

    @property
    def app(self) -> FastAPI:
        return self._app

    async def start(self) -> dict[str, Any]:
        """Resolve a free port and prepare uvicorn (call :meth:`serve` to block)."""
        for attempt in range(MAX_PORT_ATTEMPTS):
            test_port = self.port + attempt
            if not self._is_port_in_use(test_port):
                config = Config(self._app, host="127.0.0.1", port=test_port, log_level="warning")
                self._server = Server(config)
                self.actual_port = test_port
                url = f"http://127.0.0.1:{test_port}"
                logger.info("[WebUI] Starting on %s", url)
                return {"ok": True, "port": test_port, "url": url}
        raise RuntimeError(f"Could not find free Web UI port after {MAX_PORT_ATTEMPTS} attempts")

    async def serve(self) -> None:
        if self._server is None:
            raise RuntimeError("Server not started. Call start() first.")
        await self._server.serve()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            self._server = None

    @staticmethod
    def _is_port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            return sock.connect_ex(("127.0.0.1", port)) == 0
