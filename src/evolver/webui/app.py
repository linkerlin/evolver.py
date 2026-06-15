"""FastAPI WebUI entry — re-exports the unified app from :mod:`evolver.webui.server.http`.

CLI ``evolver webui`` and tests import ``app`` from here for backward compatibility.
"""

from __future__ import annotations

from evolver.webui.server.http import create_app

app = create_app()

__all__ = ["app", "create_app"]
