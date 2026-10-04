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

上面的巡游只到 solidify 看一眼门。要看**真闭环**（tick → LLM 执行 → distill → 宿主声明假说 → solidify → 真实 episode → 用该 episode 跑有/无记录消融），跑：

```bash
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_closed_loop_flash.py [--keep]
```

该脚本把模型钉死为 `deepseek-flash`（不继承 `DEEPSEEK_MODEL`，报告引用服务端实测 id），除 DeepSeek 外零网络，全部状态进一次性临时工作区。一次运行约 5 次 flash 调用。消融只用 2 道玩具题、结论止于过程指标——演示的是机制能跑通，不支撑任何效果结论（实测曾出现 `no_signal`：玩具题两臂全对，记录只加了 token；这正是机制诚实的一面）。

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

连上之后，本条消息已有别的任务就做那件事。没有别的任务时宿主调用 `swarm_boot`，再用一句话说明实际状态。`boot_once` 只登记会话，不在开机时同步技能。冻结包未装或没有基线时 boot 与 `swarm_tick` 都返回 `await_human`，已暂停时返回 `await_supervisor_resume`，都不进入循环。用户说「停」，宿主调用 `swarm_supervise` action=pause；说「继续」，宿主转达 resume。也可以对它说「启动蜂群进化」。返回的 instrument 按步执行 `swarm_tick → 执行 → swarm_distill → swarm_hypothesis → swarm_solidify → swarm_feedback`，直到终止条件。

## 首次准备

进化循环在冻结包和 Parent 基线都齐之前不会开始。下面三步在进化对话之外做。

1. 安装冻结包。

```bash
uv run evolver bench freeze
```

包写到 `$EVOLVER_HOME/anchor/bench/charter-pack.tasks.json`（默认在 `~/.evomap/anchor/bench/`）。

2. 在另一个上下文里解 val。不要在写下候选的那场对话里解，题面回到那场对话，密封就失效。打开冻结包，对每条 `split` 为 `val` 的题：

```bash
uv run evolver bench prompt <task-id> --pack "$EVOLVER_HOME/anchor/bench/charter-pack.tasks.json"
```

按打印出的提示词，把交付物写进包旁边的 `sandboxes/r1/<task-id>/` 和 `sandboxes/r2/<task-id>/`。两遍都要有。

3. 测量基线。

```bash
uv run evolver bench baseline
```

沙箱不全会退出，并列出还缺的题。成功之后回到宿主对话，再说一次要开始进化。宿主会重新 `swarm_boot`，这时才进入循环。

不想先做这三步，可以在 MCP 配置的 `env` 里设 `"EVOLVER_SWARM_GATE_HANDOFF": "hotl"`：循环照常跑，人在环上用「停」和 veto 监督。门照常拒绝并回滚每个候选，不发布任何东西。连续降级反馈仍会自动暂停（`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`，默认 3）。这个开关由人设，宿主不得自己改。

`EVOLVER_SWARM_AUTO_HIJACK=1` 不改这段文字。它强制打开 HITL，并拒绝宿主转达放行。

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
