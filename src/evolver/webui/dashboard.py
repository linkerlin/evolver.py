"""HTML dashboard generator for the Evolver WebUI.

Produces a self-contained dark-mode dashboard without external dependencies.
"""

from __future__ import annotations

import time as _time

from evolver.gep.asset_store import (
    load_capsules,
    load_genes,
    read_all_events,
    read_json_if_exists,
)
from evolver.gep.discovery import list_peers
from evolver.gep.paths import get_solidify_state_path
from evolver.webui.client.sse import render_sse_client_js
from evolver.webui.observer.github import get_open_prs, get_repo_info

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
#live-indicator {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.75rem;
  color: var(--muted);
}
#live-indicator .dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--muted);
}
#live-indicator.live .dot { background: var(--success); box-shadow: 0 0 6px var(--success); }
#live-indicator.offline .dot { background: var(--danger); }
#toast-container {
  position: fixed;
  top: 1rem; right: 1rem;
  display: flex; flex-direction: column; gap: 0.5rem;
  z-index: 1000;
}
.toast {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  font-size: 0.85rem;
  max-width: 320px;
  animation: slideIn 0.3s ease;
}
.toast.ok { border-left: 3px solid var(--success); }
.toast.fail { border-left: 3px solid var(--danger); }
@keyframes slideIn { from { transform: translateX(120%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
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
.insight-panel { font-size: 0.875rem; }
.insight-panel .muted { color: var(--muted); margin: 0; }
.insight-meta { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem; flex-wrap: wrap; }
.insight-cause { margin: 0.25rem 0; font-weight: 500; }
.insight-rec { margin: 0.25rem 0 0; color: var(--muted); }
.badge-category { background: rgba(88,166,255,0.15); color: var(--accent); }
.badge-verdict-approve { background: rgba(63,185,80,0.15); color: var(--success); }
.badge-verdict-revise { background: rgba(210,153,34,0.15); color: var(--warn); }
.badge-verdict-reject { background: rgba(248,81,73,0.15); color: var(--danger); }
.insight-table { margin-top: 0.5rem; }
.pr-state-merged { color: var(--success); }
.pr-state-open { color: var(--accent); }
.pr-state-closed { color: var(--danger); }
.pr-state-draft { color: var(--muted); }
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


def render_dashboard() -> str:  # noqa: PLR0915
    solidify = read_json_if_exists(get_solidify_state_path()) or {}
    last_run = solidify.get("last_run")
    last_solidify = solidify.get("last_solidify")
    events = read_all_events()
    genes = load_genes()
    capsules = load_capsules()

    pending = last_run is not None and last_solidify is None
    recent_events = events[-20:][::-1]
    peers = list_peers()

    def card(title: str, value: str, cls: str = "") -> str:
        return f'<div class="card"><h3>{title}</h3><div class="value {cls}">{value}</div></div>'

    header_html = f"""
    <header>
      <h1>🧬 Evolver Dashboard</h1>
      <span class="version">v1.8.0 | {len(events)} events recorded
        <span id="live-indicator" class="offline"><span class="dot"></span><span class="label">offline</span></span>
      </span>
    </header>
    """

    status_grid = f"""
    <div class="grid">
      {card("Status", "Pending" if pending else "Idle", "warn" if pending else "ok")}
      {card("Genes", str(len(genes)))}
      {card("Capsules", str(len(capsules)))}
      {card("Total Events", str(len(events)))}
      {card("Peers", str(len(peers)))}
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

    genes_section = (
        f"""
    <div class="section">
      <h2>🧪 Genes ({len(genes)})</h2>
      <table>
        <thead><tr><th>ID</th><th>Category</th><th>Risk</th><th>Score</th></tr></thead>
        <tbody>{genes_rows}</tbody>
      </table>
    </div>
    """
        if genes
        else ""
    )

    caps_rows = ""
    for c in capsules:
        cid = c.get("id", "?")
        ctype = c.get("type", "?")
        src = c.get("source", "?")
        caps_rows += f"<tr><td>{cid}</td><td>{ctype}</td><td>{src}</td></tr>\n"

    caps_section = (
        f"""
    <div class="section">
      <h2>💊 Capsules ({len(capsules)})</h2>
      <table>
        <thead><tr><th>ID</th><th>Type</th><th>Source</th></tr></thead>
        <tbody>{caps_rows}</tbody>
      </table>
    </div>
    """
        if capsules
        else ""
    )

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
        <tbody id="events-tbody">{evt_rows or '<tr><td colspan="5" style="color:var(--muted)">No events recorded yet.</td></tr>'}</tbody>
      </table>
    </div>
    """

    peers_rows = ""
    now = _time.time()
    for p in peers:
        pid = p.get("node_id", "?")
        endpoint = p.get("endpoint", "?")
        age = int(now - p.get("last_seen", 0))
        peers_rows += f"<tr><td>{pid}</td><td>{endpoint}</td><td>{age}s ago</td></tr>\n"

    insights_section = """
    <div class="section">
      <h2>🔍 Pipeline Insights</h2>
      <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));">
        <div class="card insight-panel">
          <h3>Failure Diagnosis</h3>
          <div id="insights-diagnosis"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Hub Quality Gate</h3>
          <div id="insights-hub"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Autopoiesis</h3>
          <div id="insights-autopoiesis"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Memory Sync</h3>
          <div id="insights-memory-sync"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Asset Economics</h3>
          <div id="insights-asset-econ"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>System Health</h3>
          <div id="insights-health"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Daemon Lifecycle</h3>
          <div id="insights-lifecycle"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Skills Monitor</h3>
          <div id="insights-skills-health"><p class="muted">Loading…</p></div>
        </div>
        <div class="card insight-panel">
          <h3>Persona Commentary</h3>
          <div id="insights-commentary"><p class="muted">Loading…</p></div>
        </div>
      </div>
    </div>
    """

    peers_section = f"""
    <div class="section">
      <h2>🌐 Peers ({len(peers)})</h2>
      <table>
        <thead><tr><th>Node ID</th><th>Endpoint</th><th>Last Seen</th></tr></thead>
        <tbody>{peers_rows or '<tr><td colspan="3" style="color:var(--muted)">No peers discovered.</td></tr>'}</tbody>
      </table>
    </div>
    """

    # GitHub PR panel (server-rendered; data from open_pr_registry + repo slug).
    try:
        repo_info = get_repo_info()
        open_prs = get_open_prs()
    except Exception:
        repo_info = {"available": False, "slug": None, "prUrlBase": None}
        open_prs = []
    pr_rows = ""
    pr_base = repo_info.get("prUrlBase") or ""
    for pr in open_prs:
        num = pr.get("number")
        title = pr.get("title") or ""
        head = pr.get("headRefName") or ""
        files = pr.get("fileCount", 0)
        href = f"{pr_base}/{num}" if pr_base and num else "#"
        pr_rows += (
            f"<tr><td><a href='{href}' target='_blank' rel='noopener'>#{num}</a></td>"
            f"<td>{title}</td><td>{head}</td><td>{files}</td></tr>\n"
        )
    slug_label = repo_info.get("slug") or "not configured"
    pr_section = f"""
    <div class="section">
      <h2>🔀 Pull Requests <span class="version">({slug_label})</span></h2>
      <table>
        <thead><tr><th>#</th><th>Title</th><th>Head</th><th>Files</th></tr></thead>
        <tbody>{pr_rows or '<tr><td colspan="4" style="color:var(--muted)">No open PRs (or gh/registry unavailable).</td></tr>'}</tbody>
      </table>
      <p class="muted" style="font-size:0.8rem;margin-top:0.5rem;">
        Hover status API: <code>GET /api/github/pr/&lt;n&gt;</code>
        · disable with <code>EVOLVER_WEBUI_GITHUB=0</code>
      </p>
    </div>
    """

    controls = """
    <div class="section">
      <h2>🎛️ Controls</h2>
      <div style="margin-bottom:0.75rem;">
        <input id="token-input" type="password" placeholder="WebUI token (required for run / solidify)"
          style="width:100%;padding:0.5rem;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;font-family:monospace;"
          onchange="reconnectWs()" />
      </div>
      <button onclick="sendWs({action:'run'})" style="background:var(--accent);color:#fff;border:none;padding:0.5rem 1rem;border-radius:6px;cursor:pointer;margin-right:0.5rem;">Run Cycle</button>
      <button onclick="sendWs({action:'solidify'})" style="background:var(--success);color:#fff;border:none;padding:0.5rem 1rem;border-radius:6px;cursor:pointer;margin-right:0.5rem;">Solidify</button>
      <button onclick="sendWs({action:'status'})" style="background:var(--card);color:var(--fg);border:1px solid var(--border);padding:0.5rem 1rem;border-radius:6px;cursor:pointer;">Refresh Status</button>
      <pre id="ws-log" style="margin-top:0.75rem;padding:0.75rem;background:var(--card);border-radius:6px;font-size:0.8rem;max-height:120px;overflow:auto;color:var(--muted);"></pre>
    </div>
    """

    body = f"""
    <main>
      {status_grid}
      {genes_section}
      {caps_section}
      {events_section}
      {insights_section}
      {peers_section}
      {pr_section}
      {controls}
    </main>
    <div id="toast-container"></div>
    """

    js = (
        "<script>"
        + render_sse_client_js()
        + """</script>
    <script>
    (function(){
      const indicator = document.getElementById('live-indicator');
      const container = document.getElementById('toast-container');
      const logEl = document.getElementById('ws-log');
      function setLive(live) {
        indicator.className = live ? 'live' : 'offline';
        indicator.querySelector('.label').textContent = live ? 'live' : 'offline';
      }
      function toast(msg, ok) {
        const el = document.createElement('div');
        el.className = 'toast ' + (ok ? 'ok' : 'fail');
        el.textContent = msg;
        container.appendChild(el);
        setTimeout(() => el.remove(), 6000);
      }
      function log(msg) {
        if (!logEl) return;
        logEl.textContent += msg + '\n';
        logEl.scrollTop = logEl.scrollHeight;
      }
      function esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
      }
      function verdictClass(v) {
        return v === 'approve' ? 'badge-verdict-approve' : v === 'reject' ? 'badge-verdict-reject' : 'badge-verdict-revise';
      }
      function apoStatusClass(s) {
        return s === 'stable' ? 'badge-verdict-approve' : s === 'stressed' ? 'badge-verdict-revise' : 'badge-verdict-reject';
      }
      function renderInsights(data) {
        const diagEl = document.getElementById('insights-diagnosis');
        const hubEl = document.getElementById('insights-hub');
        const apoEl = document.getElementById('insights-autopoiesis');
        const memSyncEl = document.getElementById('insights-memory-sync');
        if (!diagEl || !hubEl || !data) return;
        const d = data.failure_diagnosis;
        if (!d) {
          diagEl.innerHTML = '<p class="muted">未在 session 日志中检测到 error/traceback 签名。</p>';
        } else {
          diagEl.innerHTML =
            '<div class="insight-meta"><span class="badge badge-category">' + esc(d.category) +
            '</span><span class="muted">置信度 ' + Math.round((d.confidence || 0) * 100) + '%</span></div>' +
            '<p class="insight-cause">' + esc(d.cause) + '</p>' +
            '<p class="insight-rec">' + esc(d.recommendation) + '</p>';
        }
        const gate = data.hub_quality_gate || { services: [], assets: [] };
        const services = gate.services || [];
        const assets = gate.assets || [];
        if (!services.length && !assets.length) {
          const hit = data.hub_hit && data.hub_hit.reason ? '(Hub: ' + esc(data.hub_hit.reason) + ')' : '';
          hubEl.innerHTML = '<p class="muted">暂无 Hub 服务质量审查数据。' + hit + '</p>';
          return;
        }
        let html = '';
        if (services.length) {
          html += '<table class="insight-table"><thead><tr><th>Service</th><th>审查</th><th>分数</th></tr></thead><tbody>';
          services.forEach(function(s) {
            const rev = (s.review || {});
            html += '<tr><td>' + esc(s.service_id || '?') + '</td><td><span class="badge ' +
              verdictClass(rev.verdict) + '">' + esc(rev.verdict || '?') + '</span></td><td>' +
              esc(rev.score != null ? rev.score.toFixed(0) : '?') + '</td></tr>';
          });
          html += '</tbody></table>';
        }
        if (assets.length) {
          html += '<p class="muted" style="margin-top:0.75rem">资产校验: ' + assets.length + ' 项</p><ul>';
          assets.forEach(function(a) {
            const hv = a.hash_valid;
            const mark = hv === true ? '✓' : hv === false ? '✗' : '—';
            html += '<li>' + mark + ' ' + esc(a.asset_id || a.summary || '?') + '</li>';
          });
          html += '</ul>';
        }
        hubEl.innerHTML = html;
        if (apoEl) {
          let apoHtml = '';
          const pfa = data.preflight_abort;
          if (pfa && pfa.reason) {
            apoHtml += '<p class="insight-rec" style="color:var(--warn,#e6a700)">⚠ Preflight abort: ' +
              esc(pfa.reason) + '</p>';
          }
          const inv = data.innovation_summary;
          if (inv && inv.last_30d && !inv.last_30d.insufficient_data) {
            apoHtml += '<p class="muted">Innovation ROI (30d): ' +
              Math.round((inv.last_30d.roi || 0) * 100) + '% · rec: ' + esc(inv.recommendation) + '</p>';
          }
          const apo = data.autopoiesis;
          if (!apo) {
            apoEl.innerHTML = apoHtml + '<p class="muted">暂无 Autopoiesis 数据（等待下一进化周期）。</p>';
          } else {
            const sr = apo.self_report || {};
            const fs = sr.friction_summary || {};
            const evo = sr.evolution || {};
            const v = apo.viability || {};
            const h = apo.homeostasis || {};
            const pct = Math.round((v.score || 0) * 100);
            const actions = (h.actions || []).join(', ') || '—';
            const lm = apo.living_memory || {};
            apoEl.innerHTML = apoHtml +
              '<div class="insight-meta"><span class="badge ' + apoStatusClass(v.status || 'stressed') + '">' +
              esc(v.status || 'unknown') + '</span><span class="muted">viability ' + pct + '%</span></div>' +
              '<p class="muted">摩擦点 ' + esc(fs.total || 0) + ' · 演化规则 ' + esc(evo.evolution_count || 0) +
              ' · 活记忆 ' + esc(lm.total_friction_points || 0) + ' 条</p>' +
              '<p class="insight-rec">homeostasis: ' + esc(actions) + '</p>';
          }
        }
        if (memSyncEl) {
          const ms = data.memory_sync;
          if (!ms) {
            memSyncEl.innerHTML = '<p class="muted">暂无记忆同步数据。</p>';
          } else {
            const cats = (ms.friction_categories || []).join(', ') || '—';
            const lmCats = (ms.living_memory_categories || []).slice(0, 4).join(', ') || '—';
            const banned = (ms.banned_genes || []).join(', ') || '—';
            const lastSync = ms.last_run_friction_synced || {};
            const pfaPending = ms.preflight_abort_pending
              ? '<p class="insight-rec" style="color:var(--warn,#e6a700)">⚠ Preflight 恢复中</p>' : '';
            memSyncEl.innerHTML = pfaPending +
              '<p class="muted">活记忆 ' + esc(ms.living_memory_friction_total || 0) +
              ' 条 · 图摩擦事件 ' + esc(ms.friction_events_in_graph || 0) +
              ' · 已同步 ' + esc(ms.synced_friction_ids || 0) + '</p>' +
              '<p class="muted">摩擦类别: ' + esc(cats) + '</p>' +
              '<p class="muted">活记忆类别: ' + esc(lmCats) + '</p>' +
              '<p class="muted">禁用基因: ' + esc(banned) + '</p>' +
              '<p class="muted">偏好: ' + esc(ms.solidify_preferred_gene || ms.preferred_gene || '—') +
              ' · hints ' + esc(ms.unified_hints_count || 0) +
              (lastSync.synced ? ' · 上周期同步 ' + esc(lastSync.synced) : '') + '</p>';
          }
        }
      }
      function renderAssetEcon(data) {
        const el = document.getElementById('insights-asset-econ');
        if (!el) return;
        if (!data || !data.by_asset || !data.by_asset.length) {
          el.innerHTML = '<p class="muted">暂无资产复用数据（等待一次进化周期）。</p>';
          return;
        }
        var html = '<div class="insight-meta">' +
          '<span class="badge badge-verdict-approve">复用 ' + esc(data.total_reuse) + '</span>' +
          '<span class="badge badge-category">引用 ' + esc(data.total_reference) + '</span>' +
          '</div>' +
          '<p class="muted">节省 token: ' + esc(data.total_tokens_saved) + '</p>' +
          '<table class="insight-table"><thead><tr><th>Asset</th><th>复用</th><th>节省</th></tr></thead><tbody>';
        data.by_asset.slice(0, 5).forEach(function(a) {
          var aid = (a.asset_id || '?').slice(0, 16);
          html += '<tr><td title="' + esc(a.asset_id) + '">' + esc(aid) + '…</td>' +
            '<td>' + esc(a.reuse + a.reference) + '</td>' +
            '<td>' + esc(a.tokens_saved) + '</td></tr>';
        });
        html += '</tbody></table>';
        el.innerHTML = html;
      }
      function renderHealth(data) {
        var el = document.getElementById('insights-health');
        if (!el) return;
        if (!data || data.total === undefined || data.total === null) {
          el.innerHTML = '<p class="muted">暂无健康检查数据。</p>';
          return;
        }
        var overallCls = data.status === 'ok' ? 'ok' : data.status === 'warning' ? 'warn' : 'danger';
        el.innerHTML =
          '<div class="insight-meta"><span class="value ' + overallCls + '" style="font-size:1.25rem">' +
          esc(data.status || '?') + '</span></div>' +
          '<p class="muted">' + esc(data.ok) + ' ok · ' + esc(data.warning) + ' warn · ' + esc(data.critical) + ' crit</p>' +
          '<p class="muted">总计 ' + esc(data.total) + ' 项检查</p>';
      }
      function renderLifecycle(data) {
        var el = document.getElementById('insights-lifecycle');
        if (!el) return;
        if (!data || data.running === undefined) {
          el.innerHTML = '<p class="muted">暂无守护进程数据。</p>';
          return;
        }
        var stateCls = data.running ? 'badge-verdict-approve' : 'badge-verdict-reject';
        var hCls = data.healthy ? 'ok' : 'warn';
        var proxyCls = data.proxy_healthy ? 'ok' : 'warn';
        var silence = data.silence_minutes != null ? data.silence_minutes + 'm' : '—';
        el.innerHTML =
          '<div class="insight-meta"><span class="badge ' + stateCls + '">' + (data.running ? 'running' : 'stopped') + '</span>' +
          '<span class="muted">PIDs ' + esc(data.pid_count) + '</span></div>' +
          '<p class="muted">健康: <span class="value ' + hCls + '" style="font-size:0.875rem">' +
          (data.healthy ? 'ok' : 'degraded') + '</span> · 静默: ' + esc(silence) + '</p>' +
          '<p class="muted">代理: <span class="value ' + proxyCls + '" style="font-size:0.875rem">' +
          (data.proxy_healthy ? 'healthy' : 'down') + '</span></p>';
      }
      function renderSkillsHealth(data) {
        var el = document.getElementById('insights-skills-health');
        if (!el) return;
        if (!data) {
          el.innerHTML = '<p class="muted">暂无技能健康数据。</p>';
          return;
        }
        if (data.error) {
          el.innerHTML = '<p class="muted">' + esc(data.error) + '</p>';
          return;
        }
        var okCount = data.healthy_count || data.ok || 0;
        var total = data.total || 0;
        var issues = (data.issues || []).slice(0, 4);
        var overall = data.healthy !== false ? 'ok' : 'warn';
        el.innerHTML =
          '<div class="insight-meta"><span class="value ' + overall + '" style="font-size:1.25rem">' +
          esc(okCount) + '/' + esc(total) + '</span><span class="muted"> healthy</span></div>' +
          (issues.length ? '<ul style="margin:0.25rem 0;padding-left:1.2rem;">' +
            issues.map(function(i) {
              return '<li style="font-size:0.8rem">' + esc(i.skill || i.skill_id || i.id || '?') + ': ' + esc(i.issue || i.status || '?') + '</li>';
            }).join('') + '</ul>' : '<p class="muted">无健康问题。</p>') +
          '<p class="muted" style="font-size:0.75rem;margin-top:0.5rem;">' +
          '<a href="/api/skills/health" style="color:var(--accent)">完整报告</a> · ' +
          '<a href="/api/skills/monitor" style="color:var(--accent)">运行诊断</a></p>';
      }
      function renderCommentary(data) {
        var el = document.getElementById('insights-commentary');
        if (!el) return;
        if (!data || data.error || !data.commentaries || !Object.keys(data.commentaries).length) {
          el.innerHTML = '<p class="muted">暂无周期评述数据（等待一次 solidify）。</p>';
          return;
        }
        var gene = esc(data.gene_id || '?');
        var html = '<p class="muted" style="font-size:0.75rem">基因: ' + gene + ' · ' + esc(data.timestamp || '') + '</p>';
        var icons = {pragmatist: '⚙', explorer: '🔭', critic: '🔍'};
        ['pragmatist', 'explorer', 'critic'].forEach(function(persona) {
          var text = data.commentaries[persona] || '';
          var cls = persona === 'critic' ? 'badge-category' : 'badge-verdict-approve';
          html += '<div style="margin:0.25rem 0;font-size:0.8rem">' +
            '<span class="badge ' + cls + '">' + (icons[persona] || '') + ' ' + esc(persona) + '</span> ' +
            esc(text) + '</div>';
        });
        el.innerHTML = html;
      }
      function scheduleInsightsRefresh() {
        if (_insightsRefreshTimer) return;
        _insightsRefreshTimer = setTimeout(function() {
          _insightsRefreshTimer = null;
          refreshInsights();
        }, 500);
      }
      function refreshInsights() {
        fetch('/api/insights').then(function(r) { return r.json(); }).then(renderInsights).catch(function() {
          var diagEl = document.getElementById('insights-diagnosis');
          var hubEl = document.getElementById('insights-hub');
          var apoEl = document.getElementById('insights-autopoiesis');
          var memSyncEl = document.getElementById('insights-memory-sync');
          var econEl = document.getElementById('insights-asset-econ');
          if (diagEl) diagEl.innerHTML = '<p class="muted">无法加载 insights</p>';
          if (hubEl) hubEl.innerHTML = '<p class="muted">无法加载 insights</p>';
          if (apoEl) apoEl.innerHTML = '<p class="muted">无法加载 insights</p>';
          if (memSyncEl) memSyncEl.innerHTML = '<p class="muted">无法加载 insights</p>';
          if (econEl) econEl.innerHTML = '<p class="muted">无法加载 insights</p>';
        });
        fetch('/api/asset-reuse').then(function(r) { return r.json(); }).then(renderAssetEcon).catch(function() {
          var el = document.getElementById('insights-asset-econ');
          if (el) el.innerHTML = '<p class="muted">无法加载资产复用数据</p>';
        });
        fetch('/api/health/summary').then(function(r) { return r.json(); }).then(renderHealth).catch(function() {
          var el = document.getElementById('insights-health');
          if (el) el.innerHTML = '<p class="muted">无法加载健康数据</p>';
        });
        fetch('/api/lifecycle/summary').then(function(r) { return r.json(); }).then(renderLifecycle).catch(function() {
          var el = document.getElementById('insights-lifecycle');
          if (el) el.innerHTML = '<p class="muted">无法加载守护进程数据</p>';
        });
        fetch('/api/skills/health').then(function(r) { return r.json(); }).then(renderSkillsHealth).catch(function() {
          var el = document.getElementById('insights-skills-health');
          if (el) el.innerHTML = '<p class="muted">无法加载技能健康数据</p>';
        });
        fetch('/api/commentary/all').then(function(r) { return r.json(); }).then(renderCommentary).catch(function() {
          var el = document.getElementById('insights-commentary');
          if (el) el.innerHTML = '<p class="muted">无法加载评述数据</p>';
        });
      }
      let ws = null;
      function connectWs() {
        if (ws) { try { ws.close(); } catch(e) {} }
        const token = document.getElementById('token-input').value.trim();
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        let url = proto + '//' + location.host + '/ws';
        if (token) url += '?token=' + encodeURIComponent(token);
        ws = new WebSocket(url);
        ws.onopen = () => { setLive(true); log('WS connected'); };
        ws.onclose = () => { setLive(false); log('WS disconnected'); };
        ws.onerror = () => { setLive(false); log('WS error'); };
        ws.onmessage = function(e) {
          try {
            const data = JSON.parse(e.data);
            if (data.type === 'pong') return;
            if (data.type === 'connected') { log('Clients: ' + data.clients); return; }
            if (data.type === 'status') { toast(data.message, true); log(data.message); }
            if (data.type === 'error') { toast(data.message, false); log('ERR: ' + data.message); }
            if (data.type === 'event') {
              const status = (data.data.outcome || {}).status || 'unknown';
              toast('New event: ' + (data.data.gene_id || data.data.id || '?') + ' → ' + status, status === 'success');
            }
          } catch(err) {}
        };
      }
      window.reconnectWs = connectWs;
      window.sendWs = function(obj) {
        if (!ws || ws.readyState !== WebSocket.OPEN) { toast('WebSocket not connected', false); return; }
        ws.send(JSON.stringify(obj));
      };
      connectWs();
      refreshInsights();
      setInterval(refreshInsights, 30000);
      if (window.EvolverSSE) {
        EvolverSSE.onConnect(function(live) {
          if (!indicator) return;
          indicator.className = live ? 'live' : 'offline';
          indicator.querySelector('.label').textContent = live ? 'sse live' : 'offline';
        });
        EvolverSSE.onEvent(function(evt) {
          const tbody = document.getElementById('events-tbody');
          if (!tbody || !evt) return;
          const eid = String(evt.id || '?').slice(0, 16);
          const ts = evt.timestamp || '?';
          const gid = evt.gene_id || '?';
          const status = (evt.outcome || {}).status || '?';
          const br = evt.blast_radius || {};
          const files = br.files != null ? br.files : '?';
          const lines = br.lines != null ? br.lines : '?';
          const tr = document.createElement('tr');
          tr.innerHTML = '<td>' + eid + '…</td><td>' + ts + '</td><td>' + gid +
            '</td><td><span class="value ' + (status === 'success' ? 'ok' : 'warn') +
            '" style="font-size:0.875rem">' + status + '</span></td><td>' +
            files + ' / ' + lines + '</td>';
          tbody.insertBefore(tr, tbody.firstChild);
          toast('New event: ' + gid + ' → ' + status, status === 'success');
          scheduleInsightsRefresh();
        });
        EvolverSSE.connect('/events/stream');
      }
    })();
    </script>
    """
    )

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
{js}
</body>
</html>
"""
