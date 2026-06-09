"""HTML dashboard generator for the Evolver WebUI.

Produces a self-contained dark-mode dashboard without external dependencies.
"""

from __future__ import annotations

from evolver.gep.asset_store import (
    load_capsules,
    load_genes,
    read_all_events,
    read_json_if_exists,
)
from evolver.gep.paths import get_solidify_state_path


_CSS = """
:root {
  --bg: #0d1117;
  --fg: #c9d1d9;
  --accent: #58a6ff;
  --muted: #8b949e;
  --border: #30363d;
  --card: #161b22;
  --success: #3fb950;
  --warn: #d29922;
  --danger: #f85149;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.5;
}
header {
  padding: 1.5rem 2rem;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
header h1 { margin: 0; font-size: 1.25rem; }
header span.version { color: var(--muted); font-size: 0.85rem; }
main { padding: 1.5rem 2rem; max-width: 1200px; margin: 0 auto; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem 1.25rem;
}
.card h3 { margin: 0 0 0.5rem; font-size: 0.75rem; text-transform: uppercase; color: var(--muted); letter-spacing: 0.05em; }
.card .value { font-size: 1.75rem; font-weight: 600; }
.card .value.ok { color: var(--success); }
.card .value.warn { color: var(--warn); }
.card .value.danger { color: var(--danger); }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
th, td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-weight: 500; }
tr:hover { background: rgba(88,166,255,0.05); }
.section { margin-bottom: 2.5rem; }
.section h2 { font-size: 1rem; margin: 0 0 0.75rem; display: flex; align-items: center; gap: 0.5rem; }
.badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.badge-repair { background: rgba(248,81,73,0.15); color: var(--danger); }
.badge-optimize { background: rgba(88,166,255,0.15); color: var(--accent); }
.badge-innovate { background: rgba(63,185,80,0.15); color: var(--success); }
.badge-default { background: rgba(139,148,158,0.15); color: var(--muted); }
footer { padding: 1.5rem 2rem; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.8rem; text-align: center; }
"""


def _status_badge_class(risk: str) -> str:
    return {
        "low": "badge-optimize",
        "medium": "badge-default",
        "high": "badge-repair",
    }.get(risk or "", "badge-default")


def _event_status_class(status: str) -> str:
    return {
        "success": "ok",
        "failed": "danger",
    }.get(status or "", "warn")


def render_dashboard() -> str:
    solidify = read_json_if_exists(get_solidify_state_path()) or {}
    last_run = solidify.get("last_run")
    last_solidify = solidify.get("last_solidify")
    events = read_all_events()
    genes = load_genes()
    capsules = load_capsules()

    pending = last_run is not None and last_solidify is None
    recent_events = events[-20:][::-1]

    def card(title: str, value: str, cls: str = "") -> str:
        return f'<div class="card"><h3>{title}</h3><div class="value {cls}">{value}</div></div>'

    header_html = f"""
    <header>
      <h1>🧬 Evolver Dashboard</h1>
      <span class="version">v1.8.0 | {len(events)} events recorded</span>
    </header>
    """

    status_grid = f"""
    <div class="grid">
      {card("Status", "Pending" if pending else "Idle", "warn" if pending else "ok")}
      {card("Genes", str(len(genes)))}
      {card("Capsules", str(len(capsules)))}
      {card("Total Events", str(len(events)))}
    </div>
    """

    genes_rows = ""
    for g in genes:
        gid = g.get("id", "?")
        cat = g.get("category", "?")
        risk = g.get("risk_level", "?")
        score = g.get("score", "?")
        badge = _status_badge_class(risk)
        genes_rows += f"<tr><td>{gid}</td><td>{cat}</td><td><span class='badge {badge}'>{risk}</span></td><td>{score}</td></tr>\n"

    genes_section = f"""
    <div class="section">
      <h2>🧪 Genes ({len(genes)})</h2>
      <table>
        <thead><tr><th>ID</th><th>Category</th><th>Risk</th><th>Score</th></tr></thead>
        <tbody>{genes_rows}</tbody>
      </table>
    </div>
    """ if genes else ""

    caps_rows = ""
    for c in capsules:
        cid = c.get("id", "?")
        ctype = c.get("type", "?")
        src = c.get("source", "?")
        caps_rows += f"<tr><td>{cid}</td><td>{ctype}</td><td>{src}</td></tr>\n"

    caps_section = f"""
    <div class="section">
      <h2>💊 Capsules ({len(capsules)})</h2>
      <table>
        <thead><tr><th>ID</th><th>Type</th><th>Source</th></tr></thead>
        <tbody>{caps_rows}</tbody>
      </table>
    </div>
    """ if capsules else ""

    evt_rows = ""
    for e in recent_events:
        eid = e.get("id", "?")[:16]
        ts = e.get("timestamp", "?")
        gid = e.get("gene_id", "?")
        status = (e.get("outcome") or {}).get("status", "?")
        br = e.get("blast_radius", {})
        files = br.get("files", "?")
        lines = br.get("lines", "?")
        status_cls = _event_status_class(status)
        evt_rows += f"<tr><td>{eid}…</td><td>{ts}</td><td>{gid}</td><td><span class='value {status_cls}' style='font-size:0.875rem'>{status}</span></td><td>{files} / {lines}</td></tr>\n"

    events_section = f"""
    <div class="section">
      <h2>📜 Recent Events ({len(recent_events)})</h2>
      <table>
        <thead><tr><th>ID</th><th>Timestamp</th><th>Gene</th><th>Status</th><th>Blast Radius</th></tr></thead>
        <tbody>{evt_rows or '<tr><td colspan=\"5\" style=\"color:var(--muted)\">No events recorded yet.</td></tr>'}</tbody>
      </table>
    </div>
    """

    body = f"""
    <main>
      {status_grid}
      {genes_section}
      {caps_section}
      {events_section}
    </main>
    """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evolver Dashboard</title>
<style>{_CSS}</style>
</head>
<body>
{header_html}
{body}
<footer>Evolver WebUI — GEP v1.8.0</footer>
</body>
</html>
"""
