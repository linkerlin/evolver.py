# Proxy Quickstart

> Start the **A2A Proxy** — the local HTTP gateway between your evolver node and the Hub.

## Prerequisites

- Python 3.12+ and `uv` installed
- A completed `evolver login` (or Hub credentials in `.env`)
- Basic understanding of REST APIs

## 1. Start the proxy

```bash
# Default: listen on 127.0.0.1:8081
uv run evolver proxy

# Custom port
uv run evolver proxy --port 9090

# Custom host
uv run evolver proxy --host 0.0.0.0 --port 8081
```

The proxy starts and:
- Registers with the Hub via a `/v1/a2a/proxy/hello` heartbeat
- Begins polling for tasks and events
- Exposes the full A2A protocol at `http://127.0.0.1:8081/v1/a2a/`
- Manages local mailbox, asset store, and ATP order book

## 2. Mint a proxy token

```bash
# Generate and print a proxy token
uv run evolver proxy-token

# JSON output for scripting
uv run evolver proxy-token --json

# With sync client disabled
uv run evolver proxy-token --no-sync-client
```

The token is used by tools and IDEs to authenticate with the proxy.

## 3. Interact with the proxy (curl examples)

### Health check

```bash
curl http://127.0.0.1:8081/v1/a2a/proxy/status
# {"status":"ok","uptime_seconds":1234,"connected":true}
```

### Mailbox — fetch messages

```bash
curl http://127.0.0.1:8081/v1/a2a/mailbox/inbox
# {"messages":[...]}
```

### Asset store — list genes

```bash
curl "http://127.0.0.1:8081/v1/a2a/assets/genes?page=1&limit=20"
```

### Asset — fetch by ID

```bash
curl http://127.0.0.1:8081/v1/a2a/assets/gene/g-7
```

### ATP — check balance

```bash
curl http://127.0.0.1:8081/v1/a2a/atp/balance
```

### Tasks — list pending

```bash
curl http://127.0.0.1:8081/v1/a2a/tasks
```

## 4. LLM relay (Anthropic → Bedrock passthrough)

The proxy can relay LLM requests:

```bash
curl -X POST http://127.0.0.1:8081/v1/a2a/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

The proxy forwards to Anthropic API (or Bedrock if configured), caches responses, and records traces.

## 5. Full lifecycle management

```bash
# Check proxy health (separate from daemon health)
curl http://127.0.0.1:8081/v1/a2a/proxy/status

# See WebUI dashboard for proxy status
uv run evolver webui
# → "Daemon Lifecycle" panel shows proxy_healthy

# Check daemon health
uv run evolver check
```

## 6. Environment configuration

```bash
# Proxy-specific env vars
EVOLVER_PROXY_PORT=8081          # Default port
A2A_HUB_URL=https://evomap.ai    # Hub endpoint
EVOMAP_PROXY_TOKEN=...           # Proxy auth token (auto-minted if missing)
A2A_NODE_SECRET_VERSION=1        # Node key version (incremented on rotation)
EVOLVER_ANTI_ABUSE_TELEMETRY=heartbeat  # Anti-abuse telemetry mode

# Hub event delivery
EVOLVER_EVENT_POLL_INTERVAL_MS=5000     # Event poll interval
EVOLVER_SSE_RECONNECT_MS=30000          # SSE reconnect delay
```

## 7. Troubleshooting

| Symptom | Solution |
|---------|----------|
| "address already in use" | Another proxy or service is using port 8081; `--port 9090` |
| Hub unreachable | Check `A2A_HUB_URL` and network; proxy retries with exponential backoff |
| Token expired | Run `evolver proxy-token` to mint a new one |
| Proxy starts but no tasks appear | Hub may have no tasks assigned; check `evolver sync` |
| "node secret mismatch" | Run `evolver reset-local-secret` or check `A2A_NODE_SECRET_VERSION` |
