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

  app.init = function() {
    console.log('Evolver Dashboard v' + app.version);
    app.bindEvents();
    app.renderStatusBadge();
    if (window.EvolverSSE) {
      window.EvolverSSE.onEvent(window.EvolverSSE.appendEvent);
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
