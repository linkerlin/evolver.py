# ATP Quickstart — 本地商业闭环演练

演示 ATP 自动下单、交付与心跳信号处理（全部可在本地 mock，无需真实 Hub 账户）。

## 1. 种子商家与账本

```bash
uv run python scripts/seed_merchants.py --credit 50 \
  --output examples/atp-quickstart/workspace/atp_services.json
```

## 2. 启用自动买家

```bash
export EVOLVER_ATP_AUTOBUY=1
export EVOLVER_FF_ENABLE_AUTO_BUYER=true
```

或在 Python 中：

```python
from evolver.atp import auto_buyer
auto_buyer.set_consent(True)
```

## 3. 运行演示脚本

```bash
export OPENCLAW_WORKSPACE="$(pwd)/examples/atp-quickstart/workspace"
export EVOLVER_NO_PARENT_GIT=1
uv run python examples/atp-quickstart/demo_atp_loop.py
```

## 4. 启动 Proxy（可选）

真实 Hub 集成时：

```bash
uv run evolver proxy
```

Proxy 启动后将：

- 发送 `hello` + 心跳（`EVOLVER_PROXY_LIFECYCLE=1` 默认开启）
- 在心跳响应上运行 `heartbeat_signals_handler`（下单 / 交付）
- 后台 `AutoDeliver` 轮询（`EVOLVER_ATP_AUTODELIVER=1`）

## 相关环境变量

| 变量 | 说明 |
|---|---|
| `EVOLVER_ATP_AUTOBUY` | 启用自动买家 |
| `EVOLVER_ATP_DAILY_BUDGET` | 每日预算上限 |
| `EVOLVER_ATP_AUTODELIVER` | 自动交付循环（默认开） |
| `EVOLVER_PROXY_LIFECYCLE` | Proxy Hub 心跳（默认开） |
