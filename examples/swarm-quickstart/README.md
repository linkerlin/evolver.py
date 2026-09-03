# Swarm Quickstart（蜂群进化快速上手）

> 让宿主 Agent（ZCode / Claude Code / Cursor / …）经 MCP 接管为进化工作节点——引擎负责信号/选择/验证门，宿主负责执行 GEP 变异提示词。本示例用一个脚本走完**整个闭环**，无需 IDE。

## 前置

```bash
uv sync                 # 核心引擎（MCP server 无 fastapi 依赖）
```

## 一分钟体验：脚本驱动完整闭环

```bash
# 默认：本地样例执行器（确定性，无需 LLM）
uv run python examples/swarm-quickstart/demo_swarm_loop.py

# 进阶：DeepSeek (deepseek-v4-flash) 真实执行 GEP dispatch 提示词
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm
```

脚本会在临时 git 工作区里经真实 stdio MCP server 走完：

```
swarm_boot ─▶ swarm_status ─▶ swarm_hook_event(信号采集)
          ─▶ swarm_skills(scan/sync：捆绑技能 → 技能基因)
          ─▶ swarm_tick(产出 GEP 变异提示词)
          ─▶ 执行器（本地样例 或 DeepSeek）─▶ swarm_distill(蒸馏入库)
          ─▶ swarm_solidify(验证门) ─▶ swarm_feedback(评估信号 E)
          ─▶ supervise pause → tick 拒绝 → resume（HOTL 监督演示）
```

每一步打印可读转录；结束输出总结表。捆绑技能 `skills/demo-fix-import/`
演示 SKILL.md → 技能基因的生态桥（project > user > builtin 优先级）。

## 把你的宿主接入蜂群

三份可抄配置在 [`mcp-host-configs/`](mcp-host-configs/)：

| 文件 | 宿主 | 放置位置 |
|---|---|---|
| `zcode-settings.json` | ZCode | 工作区/用户级 settings 的 `mcpServers` |
| `claude-code.mcp.json` | Claude Code | 项目根 `.mcp.json` |
| `cursor-mcp.json` | Cursor | `.cursor/mcp.json` |

接入后对宿主说「启动蜂群进化」，或让它调用 `evolver_swarm` prompt / `swarm_boot` 工具——接管协议（instrument prompt）会指导它执行 `swarm_tick → 执行 → swarm_distill → swarm_solidify → swarm_feedback` 循环，直到终止条件。

无人值守模式：宿主环境变量加 `EVOLVER_SWARM_AUTO_HIJACK=1`，连接即注入接管指令。

## 运维手册（人在环上）

进化运行时，人类随时可以踩刹车 / 否决 / 转向：

```bash
evolver supervise status                     # 监督面板（状态/directives/vetoes）
evolver supervise pause --reason "检查一下"   # 暂停：tick 拒绝新周期
evolver supervise direct "优先稳定测试"       # 转向：注入下轮选择
evolver supervise veto "gene_xxx"            # 否决：命中即扣发提示词/阻断固化
evolver supervise resume                     # 恢复

evolver hitl list                            # 高危审批（skip_validation）
evolver hitl approve --id hitl_xxx
```

安全语义：HITL（人在环内）阻塞单个高危动作，超时 fail-safe 拒绝；HOTL（人在环上）不阻塞运行，靠干预行使权力；连续 3 次降级反馈自动暂停（绊线，`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` 可调）。

## 相关文档

- [README — MCP Swarm Evolution](../../README.md#mcp-swarm-evolution蜂群进化)
- [examples/ide-hooks/](../ide-hooks/) — 文件钩子（信号自动采集的另一轨）
- [examples/skill2recipe/](../skill2recipe/) — 技能组合为 GEP Recipe
