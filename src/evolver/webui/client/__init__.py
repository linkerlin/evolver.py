"""WebUI client subsystem — browser-side assets and dynamic HTML templates.

Equivalent to Node's ``evolver/src/webui/client/``.
"""

from evolver.webui.client.bootstrap import BOOTSTRAP_JS
from evolver.webui.client.common import COMMON_JS
from evolver.webui.client.i18n import I18N_JS
from evolver.webui.client.index_html import render_index_html
from evolver.webui.client.sse import (
    API_LOGS_PATH,
    EVENTS_STREAM_PATH,
    SSE_CLIENT_JS,
    render_sse_client_js,
)
from evolver.webui.client.static import static_routes
from evolver.webui.client.styles_css import DARK_THEME_CSS

__all__ = [
    "API_LOGS_PATH",
    "BOOTSTRAP_JS",
    "COMMON_JS",
    "DARK_THEME_CSS",
    "EVENTS_STREAM_PATH",
    "I18N_JS",
    "SSE_CLIENT_JS",
    "render_index_html",
    "render_sse_client_js",
    "static_routes",
]
