"""Dynamic HTML template generation for the WebUI dashboard.

Injects initial state (system status, asset counts, recent events)
into a self-contained HTML page so the client can render immediately
without an extra API round-trip.
"""

from __future__ import annotations

import json
from typing import Any

from evolver.webui.client.styles_css import DARK_THEME_CSS

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Evolver Dashboard</title>
<style>{css}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>🧬 Evolver Dashboard</h1>
    <span class="status-badge" id="status-badge">{overall_status}</span>
  </header>
  <main>
    <section class="card">
      <h2>System Status</h2>
      <pre id="status-json">{status_json}</pre>
    </section>
    <section class="card">
      <h2>Assets</h2>
      <p>Genes: <strong>{gene_count}</strong></p>
      <p>Capsules: <strong>{capsule_count}</strong></p>
    </section>
    <section class="card">
      <h2>Recent Events</h2>
      <ul id="event-list">
        {event_items}
      </ul>
    </section>
    <section class="card" id="insights-section">
      <h2>Pipeline Insights</h2>
      <div id="insights-diagnosis"><p class="muted">Loading…</p></div>
      <hr style="border-color:var(--border);margin:1rem 0">
      <h3 style="font-size:0.9rem;margin:0 0 0.5rem">Hub Quality Gate</h3>
      <div id="insights-hub"><p class="muted">Loading…</p></div>
      <hr style="border-color:var(--border);margin:1rem 0">
      <h3 style="font-size:0.9rem;margin:0 0 0.5rem">Autopoiesis</h3>
      <div id="insights-autopoiesis"><p class="muted">Loading…</p></div>
    </section>
  </main>
  <footer>
    <p>Evolver.py v1.89.14 — <a href="https://github.com/evolver-ai/evolver.py">GitHub</a></p>
  </footer>
</div>
<script>
  window.__INITIAL_STATE__ = {initial_state_json};
</script>
<script src="/app.js"></script>
</body>
</html>
"""


def render_index_html(
    *,
    overall_status: str = "unknown",
    status_json: str = "{}",
    gene_count: int = 0,
    capsule_count: int = 0,
    recent_events: list[dict[str, Any]] | None = None,
    initial_state: dict[str, Any] | None = None,
) -> str:
    """Render the dashboard HTML with injected initial state."""
    events = recent_events or []
    event_items = "\n".join(
        f'<li><span class="event-type">{e.get("type", "?")}</span> {e.get("message", "")}</li>'
        for e in events[:20]
    )
    if not event_items:
        event_items = '<li class="muted">No recent events</li>'

    state = initial_state or {}

    return HTML_TEMPLATE.format(
        css=DARK_THEME_CSS,
        overall_status=overall_status,
        status_json=status_json,
        gene_count=gene_count,
        capsule_count=capsule_count,
        event_items=event_items,
        initial_state_json=json.dumps(state, ensure_ascii=False),
    )
