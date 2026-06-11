"""SSE (Server-Sent Events) client helpers for the WebUI dashboard.

Connects to ``/events/stream`` or ``/api/logs`` and dispatches parsed JSON payloads
to registered handlers.
"""

from __future__ import annotations

EVENTS_STREAM_PATH = "/events/stream"
API_LOGS_PATH = "/api/logs"

SSE_CLIENT_JS = """
(function() {
  'use strict';
  window.EvolverSSE = window.EvolverSSE || {};
  const SSE = window.EvolverSSE;
  SSE.streamPath = '__EVENT_STREAM_PATH__';
  SSE.logsPath = '__API_LOGS_PATH__';
  SSE._source = null;
  SSE._handlers = [];
  SSE._connHandlers = [];

  SSE.onEvent = function(handler) {
    if (typeof handler === 'function') SSE._handlers.push(handler);
  };

  SSE.onConnect = function(handler) {
    if (typeof handler === 'function') SSE._connHandlers.push(handler);
  };

  SSE._notifyConn = function(live) {
    SSE._connHandlers.forEach(function(h) {
      try { h(live); } catch (e) { console.error('[EvolverSSE]', e); }
    });
  };

  SSE._dispatch = function(payload) {
    SSE._handlers.forEach(function(h) {
      try { h(payload); } catch (e) { console.error('[EvolverSSE]', e); }
    });
  };

  SSE.connect = function(path) {
    SSE.disconnect();
    const url = path || SSE.streamPath;
    if (!window.EventSource) {
      console.warn('[EvolverSSE] EventSource not supported');
      return null;
    }
    SSE._source = new EventSource(url);
    SSE._source.onopen = function() { SSE._notifyConn(true); };
    SSE._source.onmessage = function(ev) {
      try { SSE._dispatch(JSON.parse(ev.data)); }
      catch (e) { console.error('[EvolverSSE] parse error', e); }
    };
    SSE._source.onerror = function() {
      SSE._notifyConn(false);
      console.warn('[EvolverSSE] connection error — will retry');
    };
    return SSE._source;
  };

  SSE.disconnect = function() {
    if (SSE._source) {
      SSE._source.close();
      SSE._source = null;
      SSE._notifyConn(false);
    }
  };

  SSE.appendEvent = function(evt) {
    const list = document.getElementById('event-list');
    if (!list || !evt) return;
    const li = document.createElement('li');
    li.textContent = (evt.type || 'event') + ': ' + (evt.id || JSON.stringify(evt).slice(0, 80));
    list.prepend(li);
  };
})();
"""


def render_sse_client_js(
    *,
    stream_path: str = EVENTS_STREAM_PATH,
    logs_path: str = API_LOGS_PATH,
) -> str:
    """Return inline JS with configured SSE endpoint paths."""
    return (
        SSE_CLIENT_JS.replace("__EVENT_STREAM_PATH__", stream_path).replace(
            "__API_LOGS_PATH__", logs_path
        )
    )


__all__ = [
    "API_LOGS_PATH",
    "EVENTS_STREAM_PATH",
    "SSE_CLIENT_JS",
    "render_sse_client_js",
]
