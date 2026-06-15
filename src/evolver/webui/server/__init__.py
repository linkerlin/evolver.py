"""WebUI server — HTTP routes and server lifecycle."""

from evolver.webui.server.http import WebUiServer, create_app
from evolver.webui.server.routes import router

__all__ = ["WebUiServer", "create_app", "router"]
