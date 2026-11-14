# Swarm Quickstart（蜂群进化快速上手）

> 让宿主智能体（Agent，如 Claude Code / Cursor / Codex / OpenCode / ZCode）经 MCP 接管为进化执行器——引擎负责信号发现、只读算子诊断、`< 3s` AST 闪电门与经验金库，宿主负责代码编辑。本示例用一个脚本走完**完整两轮闭环**，无需打开 IDE。

## 前置

```bash
uv sync                 # 核心引擎（stdio MCP server 无额外 web 依赖）
```

## 一分钟体验：脚本驱动 FSM 三工具完整闭环

```bash
# 默认：本地确定性修复（无需 LLM API Key，演示 draft_preserved -> L0 闪电全绿晋升）
uv run python examples/swarm-quickstart/demo_swarm_loop.py

# 进阶：DeepSeek (deepseek-v4-flash) 根据 GEP dispatch 提示词真实生成修复代码
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm
```

若要进一步体验**带受控消融桥接的端到端实验闭环**（真实 episode 产出后立即经 `--from-episodes` 跑有/无记录双臂对照），可运行：

```bash
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_closed_loop_flash.py [--keep]
```

`demo_swarm_loop.py` 会在一次性临时 Git 工作区里启动真实 stdio MCP server，完整演示 v1.114.0 **FSM 动态门控三工具协议**：

```
IDLE 态：evolve_status ─▶ evolve_begin(空假说预览 discovery_only=true)
       ─▶ evolve_begin(前置锁定一句人话假说 ─▶ 推 notifications/tools/list_changed 切入 ACTIVE_RUN)
ACTIVE_RUN 态：evolve_begin 物理隐藏；解锁 run_lens + evolve_settle
       ─▶ 第一轮故意不完整修改 ─▶ evolve_settle ─▶ ok=false, outcome=draft_preserved（补丁原位保留 + 3 行修复指引，金库 +0）
       ─▶ 第二轮重入 ACTIVE_RUN ─▶ run_lens(import_impact / ast_hotspot 只读诊断)
       ─▶ 修复代码 ─▶ evolve_settle(< 3s L0 AST 闪电验证全绿 ─▶ outcome=promoted + 带内 blackbox + episode_id)
       ─▶ episode_get + tool_cycle_timeline（只读审计回查）
```

每一步均输出清晰转录，结尾打印总结表；捆绑技能 `skills/demo-fix-import/` 同时展示 `SKILL.md` → GEP 技能基因的多根发现生态桥。

## 一键零配置接入宿主（`evolver init`）

在任意 Python 项目根目录运行一条命令，即可全自动探测本机已装 IDE（Claude Code / Cursor / Codex / OpenCode / ZCode），幂等注入 MCP stdio 配置与会话 Hooks，写入 `.git/info/exclude` 保持 `git status` 零污染，并在后台干净子进程（自动剥离 `*_API_KEY`）中完成项目原生基线与 Anchor 首写：

```bash
uv run evolver init          # 探测宿主、幂等写入 MCP + Hooks、后台无感自举基线（< 3s 返回）
uv run evolver status        # 纯人话查看就绪灯、守护灯、已晋升修复、节省验证耗时与工作台草稿
uv run evolver up            # 启动零干预自动驾驶守护（含自适应滑动会话与 3 轮空转休眠）
```

如需手工查阅宿主配置模板，亦可参考 [`mcp-host-configs/`](mcp-host-configs/)：

| 文件 | 宿主 | 放置位置 |
|---|---|---|
| `zcode-settings.json` | ZCode | 工作区/用户级 settings 的 `mcpServers` |
| `claude-code.mcp.json` | Claude Code | 项目根 `.mcp.json` |
| `cursor-mcp.json` | Cursor | `.cursor/mcp.json` |

### FSM 三工具宿主交互规约

连接 MCP 后，服务端通过 `notifications/tools/list_changed` 动态门控工具目录，宿主无需记忆繁琐步骤或布尔旗标：

1. **`IDLE` 态（无在途周期）**：仅暴露核心动作 `evolve_begin` 与只读 `evolve_status`（若首次连接尚未运行 `evolver init`，服务端会在后台自动懒自举基线）。
   - 调用 `evolve_begin()` 不传 `hypothesis`：执行零副作用信号探测（`discovery_only=true`），返回高优信号与推荐算子列表，状态仍停留在 `IDLE`。
   - 调用 `evolve_begin(hypothesis="...", target_files=[...])`：前置锁定本轮唯一可证伪假说，状态切换为 `ACTIVE_RUN`，并返回 `< 4,000 tokens` 高信噪比 GEP 提示词。
2. **`ACTIVE_RUN` 态（周期执行中）**：`evolve_begin` 从工具目录物理隐藏，防止重复开局；暴露只读诊断透镜 `run_lens`（内置 `ast_hotspot`、`import_impact`、`trace_locator`、`contract_surface`）与原子结算工具 `evolve_settle`。
3. **双轨原子结算（`evolve_settle`）**：
   - 默认运行 **`< 3s` L0 AST 反向依赖闪电验证**（仅针对改动文件的 `ruff` 与反向导入闭包关联的 `pytest` 文件），并在周期边界自动采集带内黑匣子（`blackbox`：前后 AST 增量、透镜调用栈、墙钟耗时），无需配置本地 HTTP 代理即可获得 100% 过程观测覆盖。
   - **金库严晋升（`ok=true`）**：验证全绿且净增益时自动结算 `episode_record`、同步 `index.sqlite` WAL 读索引并晋升资产，随后推通知切回 `IDLE`。
   - **工作台保草稿（`ok=false, outcome="draft_preserved"`）**：验证未过或适应度未胜（`drop` / `flat` / `regression`）时，工作区补丁**原位保留不回滚**（同时备份至 `rejected_stashes/<run_id>/`），返回精确到 `file:line` 的恒 3 行 `actionable_fix`，正向基因金库严格 `+0`，并切回 `IDLE` 供宿主按指引继续修复。
   - **硬阻断回滚**：仅当 diff 含密钥/凭据、触碰 `~/.evolver/` 受保护引擎状态或触发 `val_seal` 密封泄露时，强制拒绝并回滚。

此外，`episode_get`、`episode_inspect`（按问题与行号窗口只读放大被截断的检查日志）、`tool_asset_search`、`tool_asset_get` 与 `tool_cycle_timeline` 作为只读辅助工具常驻可用。

## 开箱诊断（`evolver setup` / `evolver doctor`）

除一键 `evolver init` 外，专家或 CI 环境亦可使用非破坏式诊断命令核查 Git、冻结任务包、Parent 基线与锁状态：

```bash
uv run evolver doctor          # 只读诊断：git / freeze pack / Parent baseline / user lock
uv run evolver doctor --fix    # 安全补齐冻结包；仅当沙箱已齐时测量 bench baseline
uv run evolver setup           # 等同 doctor --fix
```

`doctor` 退出码：`0` 表示 `loop_ready` 或仅首次环境缺口（`no_baseline` / `pack_absent` / `unmeasured`，允许 `soft_continue`）；`2` 表示硬阻断（如非 Git 仓库或 `user_lock` 被占用）。注意：候选进化对话里**不得解 val、不得打开 val 密封材料**（`val_seal` 硬门守护）；运行态数据一律存于源码树外的 `~/.evolver/workspaces/<id>/`，绝不自动执行 `git commit`。

### Grok Bot 路径约定

在 Grok Bot 环境中：进化工作区根为 `/workspace`，`evolver.py` 源码检出位于 `/workspace/evolver-research/evolver.py`。更新源码后请重启 `evolver mcp` 进程，以确保加载最新模块（可通过 `evolve_status.source_revision` 核对）：

```json
{
  "mcpServers": {
    "evolver-swarm": {
      "command": "uv",
      "args": [
        "--project", "/workspace/evolver-research/evolver.py",
        "run", "evolver", "mcp"
      ],
      "env": {
        "EVOLVER_REPO_ROOT": "/workspace/evolver-research/evolver.py",
        "EVOLVER_CONFIG": "{\"quiet_parent_git\": true}"
      }
    }
  }
}
```

## 运维手册（人在环上 HOTL / 人在环内 HITL）

进化运行期间，操作者随时可通过 CLI 踩刹车、下达方向指令或否决特定基因：

```bash
uv run evolver internal supervise status                     # 监督面板（状态/directives/vetoes）
uv run evolver internal supervise pause --reason "检查一下"   # 暂停：evolve_begin 拒绝开新周期
uv run evolver internal supervise direct "优先稳定测试"       # 转向：注入下轮策略选择
uv run evolver internal supervise veto "gene_xxx"            # 否决：命中即阻断派发与结算
uv run evolver internal supervise resume                     # 恢复运行

uv run evolver internal hitl list                            # 查看待批高危操作
uv run evolver internal hitl approve --id hitl_xxx
```

## 相关文档

- [README — Connecting Your Host Agent](../../README.md)
- [README.zh — 接入宿主智能体](../../README.zh.md)
- [examples/ide-hooks/](../ide-hooks/) — IDE 会话钩子（信号自动采集的另一轨）
- [examples/skill2recipe/](../skill2recipe/) — 技能组合为 GEP Recipe
