# ATP Quickstart — Local Commercial Loop

Demonstrate ATP order placement, delivery, settlement, and heartbeat signal handling — all with local mock, no real Hub account needed.

## 1. Seed merchants and ledger

```bash
uv run python scripts/seed_merchants.py --credit 50 \
  --output examples/atp-quickstart/workspace/atp_services.json
```

This creates a local ATP service registry with a 50-credit merchant account.

## 2. Enable auto-buyer

```bash
export EVOLVER_ATP_AUTOBUY=1
export EVOLVER_FF_ENABLE_AUTO_BUYER=true
```

Or in Python:

```python
from evolver.atp import auto_buyer
auto_buyer.set_consent(True)
```

## 3. Run the demo script

```bash
export OPENCLAW_WORKSPACE="$(pwd)/examples/atp-quickstart/workspace"
export EVOLVER_NO_PARENT_GIT=1
uv run python examples/atp-quickstart/demo_atp_loop.py
```

The script:
1. Creates a mocked Hub (`fake_place` / `fake_submit`)
2. Runs `auto_buyer.run_tick()` — detects gaps and places orders
3. Runs `auto_deliver._handle_task()` — processes pending deliveries
4. Runs heartbeat signal handler — responds to Hub push signals
5. Prints settlement ledger summary

## 4. Start the proxy (optional, for real Hub)

With a real Hub account:

```bash
uv run evolver proxy
```

The proxy will:
- Send `hello` + heartbeat (`EVOLVER_PROXY_LIFECYCLE=1` enabled by default)
- Run `heartbeat_signals_handler` on heartbeat responses (order/deliver)
- Background `AutoDeliver` polling (`EVOLVER_ATP_AUTODELIVER=1`)

## 5. Full ATP CLI workflow

```bash
# Check balance
uv run evolver atp balance

# Deposit credits
uv run evolver atp deposit 100

# Place an order
uv run evolver buy skill-id-here --quantity 1

# List orders
uv run evolver orders --status pending

# Verify delivery
uv run evolver verify order-123

# Reject delivery
uv run evolver verify order-123 --reject

# Complete a task
uv run evolver atp-complete task-456

# View transaction history
uv run evolver atp history

# Enable/disable ATP
uv run evolver atp enable
uv run evolver atp disable

# Overall status
uv run evolver atp status

# Withdraw credits
uv run evolver atp withdraw 50
```

## 6. Monitor via WebUI

```bash
uv run evolver webui --port 8080
```

ATP-related data is available through the proxy API at:
- `GET /v1/a2a/atp/balance`
- `GET /v1/a2a/atp/orders`
- `POST /v1/a2a/atp/order`

## Related Environment Variables

| Variable | Description |
|----------|-------------|
| `EVOLVER_ATP_AUTOBUY` | Enable auto-buyer (1/true) |
| `EVOLVER_ATP_DAILY_BUDGET` | Daily spend cap |
| `EVOLVER_ATP_AUTODELIVER` | Auto-delivery loop (default on) |
| `EVOLVER_PROXY_LIFECYCLE` | Proxy Hub heartbeat (default on) |
| `EVOLVER_FF_ENABLE_AUTO_BUYER` | Feature flag for auto-buyer |
| `A2A_HUB_URL` | Hub endpoint for orders/delivery |

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "insufficient balance" | Run `seed_merchants.py` or `evolver atp deposit` |
| No merchants available | Ensure `atp_services.json` exists in workspace |
| Demo script fails to import | Run `uv sync` from repo root |
| Orders not filling | Check `EVOLVER_ATP_AUTOBUY=1` and `EVOLVER_ATP_DAILY_BUDGET` |
| Proxy health check fails | Hub may be unreachable; check `A2A_HUB_URL` |

