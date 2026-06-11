"""Dark theme CSS for the WebUI dashboard.

Responsive, accessible, self-contained stylesheet.
"""

from __future__ import annotations

DARK_THEME_CSS = """
:root {
  --bg: #0d1117;
  --fg: #c9d1d9;
  --card-bg: #161b22;
  --border: #30363d;
  --accent: #58a6ff;
  --success: #3fb950;
  --warning: #d29922;
  --danger: #f85149;
  --muted: #8b949e;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.6;
}
.container {
  max-width: 960px;
  margin: 0 auto;
  padding: 2rem 1rem;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 1rem;
}
h1 { margin: 0; font-size: 1.5rem; }
.status-badge {
  padding: 0.25rem 0.75rem;
  border-radius: 999px;
  font-size: 0.875rem;
  font-weight: 600;
  text-transform: uppercase;
  background: var(--border);
  color: var(--muted);
}
.status-badge.healthy { background: rgba(63,185,80,0.2); color: var(--success); }
.status-badge.warning { background: rgba(210,153,34,0.2); color: var(--warning); }
.status-badge.critical { background: rgba(248,81,73,0.2); color: var(--danger); }
.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.25rem;
  margin-bottom: 1rem;
}
.card h2 { margin-top: 0; font-size: 1.125rem; color: var(--accent); }
pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem;
  overflow-x: auto;
  font-size: 0.875rem;
}
ul { list-style: none; padding: 0; margin: 0; }
li { padding: 0.375rem 0; border-bottom: 1px solid var(--border); }
li:last-child { border-bottom: none; }
.event-type {
  display: inline-block;
  min-width: 6rem;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--accent);
}
.muted { color: var(--muted); }
footer { text-align: center; margin-top: 2rem; font-size: 0.875rem; color: var(--muted); }
footer a { color: var(--accent); text-decoration: none; }
@media (max-width: 600px) {
  header { flex-direction: column; align-items: flex-start; gap: 0.5rem; }
  .container { padding: 1rem; }
}
"""
