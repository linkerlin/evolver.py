"""WebUI server — HTTP routes and server lifecycle."""

from evolver.webui.server.http import WebUiServer
from evolver.webui.server.routes import router

__all__ = ["WebUiServer", "router"]
