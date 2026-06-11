"""Shared client-side utilities — date formatting, debounce, throttle.

These are rendered as inline JS snippets for the self-contained dashboard.
"""

from __future__ import annotations

COMMON_JS = """
(function() {
  'use strict';
  window.EvolverUtils = window.EvolverUtils || {};
  const U = window.EvolverUtils;

  U.formatDate = function(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return d.toLocaleString();
  };

  U.debounce = function(fn, wait) {
    let t;
    return function() {
      clearTimeout(t);
      t = setTimeout(fn, wait);
    };
  };

  U.throttle = function(fn, limit) {
    let inThrottle;
    return function() {
      if (!inThrottle) {
        fn.apply(this, arguments);
        inThrottle = true;
        setTimeout(function() { inThrottle = false; }, limit);
      }
    };
  };

  U.escapeHtml = function(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  };
})();
"""
