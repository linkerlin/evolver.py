# VISTA 机械套具 — 落地清单

> 状态：**八项已落在工作区**（2026-10-18）。不替换 [`演进方案.md`](演进方案.md) 的「经验即证据」出口，不改 `frozen_gate`，不切版本。
> 运行态（`WORKING_SESSION.md`、`working_archive/`、`compact_checkpoint.requested` / `.ready`、`hypothesis.consumed.json`、`episodes/inspect_calls.jsonl`）只落在 `<EVOLUTION_DIR>/`，不进产品 git。
> 记录分层不变：`episode_inspect` 只读引擎现场；宿主的 `question` 与 `WORKING_SESSION.md` 是线索，不进验收维。

## Tier 1 — 经验重注视与降噪

| # | 项 | 完成时 |
|---|---|---|
| P0-A | `episode_inspect`：空 question 拒绝；按行读回被 400/4000 截断的原文；输出过 `val_seal.redact`；不写指针 | 见 `gep/episode_record.py` 的 `inspect_episode_scene`，CLI `episode inspect`，MCP `episode_inspect` |
| P1-F | 诊断串量化：行号、地址、临时路径、UUID 坍缩后，同 digest 的报错在证据包渲染里并成一条并标 `count` | `gep/sanitize.py` `quantize_diagnostic_signature`；账本条数与 mandate 不并，只并渲染 |
| P1-D | `expected_outcome` 可选；`record_round` 用引擎检查结果写入 `gates.prediction_delta`，不抄宿主事后解释 | `gep/hypothesis.py` |

## Tier 2 — 防污染记忆与压缩门

| # | 项 | 完成时 |
|---|---|---|
| P0-B | `WORKING_SESSION.md` 16_000 字配额；`start` / `accept` / `incomplete` 归档后 `unlink` | `gep/working_memory.py` |
| P0-C | `compact_checkpoint.requested` 置位时，tick / distill / hypothesis / propose / solidify 返回 `checkpoint_required`；`swarm_checkpoint_working` 写草稿并清标记。连续 4 次 solidify 失败或 hook `precompact` 置位 | `gep/compact_gate.py`；Claude `PreCompact` hook |
| P1-E | 极简宪章写入 GEP prompt 与 swarm instrument。既有协议正文保留（测试与宿主都靠它）；新门禁带 `next_action` + `steer_message` | `gep/prompt.py` `EVOLVER_CHARTER` |

## Tier 3 — 沙盒与效率标尺

| # | 项 | 完成时 |
|---|---|---|
| P2-G | 评分子进程剥离 `*_API_KEY` 与名单内的控制变量。已落地的 run（`last_solidify` 已对准且已有 episode）再次 `swarm_solidify` 只回 episode id，不再跑级联 | 仍 pending 的失败 run 可以再 solidify：那是现有重试路径，封死会让 boot 的「先 solidify」死循环 |
| P2-H | `rere_score`（`r_ref=2`，上限 1.15）进 `meta-report` 的 `panel.rere`。不进验收门 | `experiment/metrics.py` |

## 第二轮（评审六条）

| # | 项 | 完成时 |
|---|---|---|
| R1 | MCP `swarm_hook_event` 的 `event` 枚举补 `precompact` | `test_mcp_protocol.py` 走真 stdio：置标记 → distill 被拒 → checkpoint 放行 |
| R2a | solidify 过门时不再直接删假说，改为 `consume_hypothesis(run_id)`：移到 `hypothesis.consumed.json` 并盖上消费它的 run。门只读 `hypothesis.json`，旧假说照旧过不了下一轮 | 之前真路径上 `prediction_delta` 从未写入（门在跑检查前就删了假说）；`test_solidify.py` 走真 `solidify()` 钉住 |
| R2b | `render_episode_block` 仅在 `gates.prediction_delta` 存在时多一行；无此字段时字节不变。没有检查结果时 `matched=None`，不判落空 | instrument 的假说示例补可选 `expected_outcome`，否则宿主不会声明 |
| R3 | dispatch 的 `## Host Clues` 在证据包之后带 `- [host_working]`，上限 3_000 字（`PROMPT_MAX_CHARS=24_000`，整段 16_000 会挤掉尾部的 Selected Gene 与输出格式）；超出部分标注由 `swarm_boot` 返回全文（`working_session_text`） | |
| R4 | Claude `PreCompact` hook 输出 `{"decision":"block",...}`，写完 checkpoint 才放行一次；同一请求只拦一次，宿主不理会时放行，标记保留、变异工具照旧锁住，不会把满上下文卡死。hook 子进程先走 `maybe_route_to_soak()`，与 MCP 进程看同一个 `EVOLUTION_DIR` | `compact_gate.precompact_decision` |
| R5 | MCP `episode_inspect` 成功时在 `<EVOLUTION_DIR>/episodes/inspect_calls.jsonl` 记一行（episode、cycle run、当时运行中的配对会话 run、view 种类；不记 question）。`inspect_episode_scene` 本身仍只读；CLI 调用是人，不计。`meta-report` 的 `improver_tools` 多 `episode_inspect_calls` / `episode_inspect_sessions` | 会话 run id 是和 `panel.rere` 关联的键 |
| R6 | 真实 MCP 闭环产出带截断锚点与 `prediction_delta` 的 episode，再跑 `experiment --ablation --from-episodes --placebo` | 仓外沙盒 `C:\Temp\evolver-r6\`，宿主经真 stdio 调 `evolver mcp`。种子含两个 bug，本轮只修一个，`expected_outcome` 声明 pytest 会过。episode `sha256:23c67dce…`（953 字符）带 `matched=False unmet=["pytest"]` 与「pytest stdout truncated at 400/2208」锚点；`episode_inspect` 读回截断后的真实失败（裸数字 `'45'`、`' 7 '`），侧日志记一行。初版 `tasks.json` 因选项文字自带提示而饱和（第二次采样 8/8 对 8/8）。重做对称不泄题的 [`tasks_grounded.json`](file:///C:/Temp/evolver-r6/tasks_grounded.json)（`digest=sha256:a4ca0586…`，6 道过程决策 + 2 道对照，选项中 `ruff`/`mypy`/`pytest`/`none` 完全对称）并在 `commit=c21db58801dd` 上跑 `--stage-exit --from-episodes --placebo`：两次独立交错种子（`seed=7` 与 `seed=13`）均稳定复现 **`with_records` 8/8 对 `without_records` 2/8**（`paired=a_better`，`discordant=6`，`p=0.03125`，`eligible=True`；`seed=7` 耗 4263 vs 10901 tokens，`seed=13` 耗 4633 vs 4174 tokens）。因 $n=8 < 30$，`stage=inconclusive`，严格记 **indicative only**，不收阶段 |

## 验收

`uv run ruff check`、`uv run ruff format --check`、`uv run mypy`、相关 `pytest`。全量 `pytest` 以本轮改动面为准；不过则修到过。
