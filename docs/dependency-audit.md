# Dependency Audit (S25.4)

> 2026-09-01 · 演进方案_wikiskill对照版.md §S25.4 · 方法：AST/grep 全量引用扫描（`scripts` 与 `tests` 一并核查），证据见下表。
> **勘误（审阅发现）**：初版误报 boto3 "零引用"——真实情况是 `proxy/router/messages_route.py:195/226/240` 三处**惰性导入**（首轮扫描通配深度不足漏检）。boto3 实际是可选依赖（代码自带 `not-installed` 降级分支），已移入 `[project.optional-dependencies] bedrock`。
> 原则（wikiskill L8）：依赖越少，门控结论越可信；每个依赖必须回答"删掉会坏什么"。

## 结论：14 核心 → 10 核心 + 1 optional extra

### 移除（运行时零引用，三层递归扫描实测）

| 依赖 | 引用数 | 备注 |
|---|---:|---|
| `click` | **0** | CLI 实际用 argparse（`cli.py`），click 从未接入 |
| `GitPython` | **0** | 全部 git 操作走 `subprocess`（`gep/git_ops.py` 等）——本就如此，无功能损失 |
| `pydantic-settings` | **0** | 配置全部用自研 `env_str/env_int/env_bool/env_float`（`config.py`） |

### 移入 optional extras

| 依赖 | 引用 | 备注 |
|---|---|---|
| `boto3` | 3（惰性导入） | 仅 Bedrock SSE 中继使用；`messages_route.py:226` 自带 `boto3 not installed` 降级 → `evolver[bedrock]` |

### 保留（有真实引用）

| 依赖 | 引用 | 用途 | 风险备注 |
|---|---:|---|---|
| `pydantic` | 广泛 | schemas（extra=forbid） | 核心，保留 |
| `httpx[http2]` | 21 | Hub/LLM 中继客户端 | 核心，保留 |
| `cryptography` | 7 | node secret 签名/轨迹加密 | 安全边界，保留 |
| `fastapi` / `uvicorn` | 1 / 2 | proxy + webui | 可拆为 extras（见下） |
| `psutil` | 3 | 健康检查/负载守卫 | Windows load guard 依赖，保留 |
| `filelock` | 2 | 单实例锁 | 保留 |
| `python-dotenv` | 2 | .env 加载 | 保留 |
| `keyring` | 1 | workspace keychain | 单点引用——候选移入 extras（`evolver[keychain]`），非紧急 |
| `mcp` | 1 | MCP server 子命令 | 候选移入 extras（`evolver[mcp]`） |

## 后续（S30 瘦身余项，不强制当季）

1. `fastapi`/`uvicorn`/`mcp`/`keyring` 移入 `[project.optional-dependencies]`：`pip install evolver` 只装 6 个核心；`evolver[server]` 装 proxy/webui 全家。CLI 检测缺依赖时给可操作报错。
2. `docs/env-registry.md`（S25.5）的 234 个变量按 S30.4 清理后，`python-dotenv` 与自研 env 层二选一评估。
3. 每新增依赖须在 PR 中回答："删掉会坏什么？stdlib 为什么不够？"（wikiskill CONTRIBUTING 纪律）
