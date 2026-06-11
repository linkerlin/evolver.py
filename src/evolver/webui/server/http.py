"""WebUI HTTP server — serve the dashboard and API routes.

Equivalent to evolver/src/webui/server/http.js.
"""

from __future__ import annotations

import logging
import os
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
)
from evolver.webui.server.routes import router as webui_router

logger = logging.getLogger(__name__)

DEFAULT_WEBUI_PORT = 19821
MAX_PORT_ATTEMPTS = 50


class WebUiServer:
    """Self-contained WebUI server with automatic port fallback."""

    def __init__(self, port: int | None = None) -> None:
        self.port = port or int(os.environ.get("EVOLVER_WEBUI_PORT", DEFAULT_WEBUI_PORT))
        self._app = self._build_app()
        self._server: Server | None = None
        self.actual_port: int | None = None

    def _build_app(self) -> FastAPI:
        app = FastAPI(title="Evolver WebUI")
        app.include_router(webui_router, prefix="/api")

        @app.get("/", response_class=HTMLResponse)
        async def index() -> str:
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

    async def start(self) -> dict[str, Any]:
        """Start the server, trying successive ports if the first is taken."""
        for attempt in range(MAX_PORT_ATTEMPTS):
            test_port = self.port + attempt
            if not self._is_port_in_use(test_port):
                config = Config(self._app, host="127.0.0.1", port=test_port, log_level="warning")
                self._server = Server(config)
                self.actual_port = test_port
                url = f"http://127.0.0.1:{test_port}"
                logger.info("[WebUI] Starting on %s", url)
                # Run in background; caller should await serve()
                return {"ok": True, "port": test_port, "url": url}
        raise RuntimeError(f"Could not find free Web UI port after {MAX_PORT_ATTEMPTS} attempts")

    async def serve(self) -> None:
        """Blocking serve — call this after start() to keep the server running."""
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
