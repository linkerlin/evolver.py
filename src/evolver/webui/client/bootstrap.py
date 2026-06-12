"""WebUI client bootstrap — application initialization, routing, error boundaries.

Provides a small JS snippet injected into the dashboard HTML that sets up
the client-side application shell.
"""

from __future__ import annotations

BOOTSTRAP_JS = """
(function() {
  'use strict';
  window.EvolverApp = window.EvolverApp || {};
  const app = window.EvolverApp;

  app.state = window.__INITIAL_STATE__ || {};
  app.version = '1.89.2';

  app.renderInsights = function(data) {
    var diagEl = document.getElementById('insights-diagnosis');
    var hubEl = document.getElementById('insights-hub');
    var apoEl = document.getElementById('insights-autopoiesis');
    var memSyncEl = document.getElementById('insights-memory-sync');
    if (!diagEl || !hubEl || !data) return;
    var U = window.EvolverUtils || {};
    var esc = U.escapeHtml || function(s) { return String(s == null ? '' : s); };
    var d = data.failure_diagnosis;
    if (!d) {
      diagEl.innerHTML = '<p class="muted">No error signatures in session log.</p>';
    } else {
      diagEl.innerHTML = '<p><strong>' + esc(d.category) + '</strong> (' +
        Math.round((d.confidence || 0) * 100) + '%)</p><p>' + esc(d.cause) + '</p><p class="muted">' +
        esc(d.recommendation) + '</p>';
    }
    var gate = data.hub_quality_gate || { services: [], assets: [] };
    var services = gate.services || [];
    if (!services.length && !(gate.assets || []).length) {
      hubEl.innerHTML = '<p class="muted">No hub quality gate data yet.</p>';
      return;
    }
    var html = '<ul>';
    services.forEach(function(s) {
      var rev = s.review || {};
      html += '<li>' + esc(s.service_id) + ': ' + esc(rev.verdict) + ' (' + esc(rev.score) + ')</li>';
    });
    html += '</ul>';
    hubEl.innerHTML = html;
    if (apoEl) {
      var apoHtml = '';
      if (data.preflight_abort && data.preflight_abort.reason) {
        apoHtml += '<p class="muted">Preflight abort: ' + esc(data.preflight_abort.reason) + '</p>';
      }
      var apo = data.autopoiesis;
      if (!apo) {
        apoEl.innerHTML = apoHtml + '<p class="muted">No autopoiesis data yet.</p>';
      } else {
        var sr = apo.self_report || {};
        var fs = sr.friction_summary || {};
        var v = apo.viability || {};
        var pct = Math.round((v.score || 0) * 100);
        apoEl.innerHTML = apoHtml + '<p><strong>' + esc(v.status || 'unknown') + '</strong> viability ' + pct +
          '% · friction ' + esc(fs.total || 0) + '</p>';
      }
    }
    if (memSyncEl) {
      var ms = data.memory_sync;
      if (!ms) {
        memSyncEl.innerHTML = '<p class="muted">No memory sync data.</p>';
      } else {
        memSyncEl.innerHTML = '<p class="muted">friction events ' + esc(ms.friction_events_in_graph || 0) +
          ' · synced ' + esc(ms.synced_friction_ids || 0) +
          ' · hints ' + esc(ms.unified_hints_count || 0) + '</p>';
      }
    }
  };

  app._insightsRefreshTimer = null;
  app.scheduleInsightsRefresh = function() {
    if (app._insightsRefreshTimer) return;
    app._insightsRefreshTimer = setTimeout(function() {
      app._insightsRefreshTimer = null;
      app.refreshInsights();
    }, 500);
  };
  app.refreshInsights = function() {
    fetch('/api/insights').then(function(r) { return r.json(); }).then(app.renderInsights).catch(function() {});
  };

  app.init = function() {
    console.log('Evolver Dashboard v' + app.version);
    app.bindEvents();
    app.renderStatusBadge();
    app.refreshInsights();
    setInterval(app.refreshInsights, 30000);
    if (window.EvolverSSE) {
      window.EvolverSSE.onEvent(function(evt) {
        window.EvolverSSE.appendEvent(evt);
        app.scheduleInsightsRefresh();
      });
      window.EvolverSSE.connect();
    }
  };

  app.bindEvents = function() {
    document.querySelectorAll('.card h2').forEach(function(h) {
      h.style.cursor = 'pointer';
      h.addEventListener('click', function() {
        const card = h.closest('.card');
        card.classList.toggle('collapsed');
      });
    });
  };

  app.renderStatusBadge = function() {
    const badge = document.getElementById('status-badge');
    if (!badge) return;
    const status = app.state.overall_status || 'unknown';
    badge.className = 'status-badge ' + status;
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', app.init);
  } else {
    app.init();
  }
})();
"""
