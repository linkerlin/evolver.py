# evolver.py 记忆机制 与 OpenClaw 三层记忆架构 —— 对齐对比报告

> **论点**：evolver.py 之记忆子系统，可被解读为 OpenClaw 三层记忆模型在**进化自修改场景**下的同构特化实现。两者共享"文件即真值源、分层蒸馏、Agent 自维护、衍生索引"四大设计哲学；差异主要源于**目标场景**（对话连续性 vs. 实验结局追踪），而非架构本体的分歧。

---

## 一、总体对齐判定

| 对齐维度 | 强度 | 说明 |
|---|---|---|
| 设计哲学（File-first / Tiered / Agent-maintained） | ★★★★★ | 几乎完全同源 |
| 三层结构同构（L1/L2/L3） | ★★★★☆ | 可建立一一对应，仅 L1 形态不同 |
| 辅助机制（Flush / Dreaming / Search） | ★★★★☆ | 三个机制皆可对位 |
| 数据格式（Markdown + YAML frontmatter） | ★★★★★ | 几乎逐字对应 |
| 写回/晋升触发条件 | ★★★★☆ | 触发点不同，模式相同 |
| 检索手段（向量 vs. 内容哈希） | ★★☆☆☆ | 实现不同，但都属"衍生索引" |

**结论**：表层与哲学层面**高度同源**；深层机制因目标场景特化而呈现差异，但**结构同构**（structural isomorphism）成立。

---

## 二、三层结构一一对应

### 2.1 L1 ── 工作记忆（Working Memory / Context Window）

| OpenClaw | evolver.py |
|---|---|
| 当前会话的 LLM 上下文窗口 | 单次进化周期内贯穿流水线的 `ctx: dict[str, Any]` |
| 系统提示词 + 用户消息 + 工具调用历史 | preflight / collect / signals / hub / enrich / autopoiesis / select / dispatch 各阶段写入 ctx 的累积字段 |
| 会话结束即丢失 | 周期结束即销毁；下周期从零开始 |
| Token 预算限制（自动压缩触发） | `guards.py` 之 RSS / 负载 / 冷却检查（同样会触发 abort） |

**对齐点**：
- 都是**进程内、单次运行 scope** 的临时状态。
- 都**不能跨周期/跨会话直接保留**——必须经 Flush 落盘才能进入 L2。
- 都受**预算约束**（Token 预算 ↔ 系统资源预算），逼近上限时触发保护机制。
- 都以 `dict` / message list 为载体（OpenClaw 用消息数组，evolver 用 ctx dict）。

**L1 → L2 的衔接载体**（与 OpenClaw "carry-over context" 同义）：
- `evolution_solidify_state.json.last_run`——上一周期的最终快照（≈ "上一次会话摘要"）。
- `pending_signals.json`——本周期待处理信号队列，由上一周期 autopoiesis 写入。
- `autopoiesis_preflight_abort.json`——周期被中断时的状态快照（≈ OpenClaw 之 pre-compaction flush 落盘）。

---

### 2.2 L2 ── 短期记忆（Daily Notes / Append-only Logs）

| OpenClaw | evolver.py |
|---|---|
| `memory/YYYY-MM-DD.md` | `memory_graph.jsonl`（主） + `events.jsonl` + `autopoiesis.jsonl` |
| 每日 Markdown 笔记，按日期切片 | 时间戳 JSONL 事件流，毫秒精度 |
| Append-only（仅追加） | Append-only（仅追加） |
| 内容：会话摘要、观察、中间发现 | 内容：signal / hypothesis / attempt / outcome / friction / epoch_boundary 事件 |
| 跨日笔记通过 `memory_search` 检索 | 跨周期事件通过 `get_memory_advice()` / `try_read_memory_graph_events()` 检索 |
| Pre-compaction flush 自动写入 | 各流水线阶段直接 append（record_signal_snapshot / record_attempt / record_outcome） |

**对齐点（关键同构）**：
- **同为 append-only 时间序列日志**——OpenClaw 按日切片，evolver 按事件切片，本质相同。
- **同承载"未经蒸馏的原始上下文"**——等待提升到 L3 的候选材料。
- **同为衍生索引的构建基础**——OpenClaw 在其上建向量索引；evolver 在其上建 `memory_graph_state.json` 之 `preferred_by_signal` 与 ban 统计。
- **同样有索引/状态副作用**：OpenClaw 触发文件监听 + 嵌入；evolver 触发 `record_signal_gene_preference` / `last_action` 更新。

**事件 kind 与 daily note 段落形态的对应**：

| `memory_graph.jsonl` 之 kind | OpenClaw `memory/YYYY-MM-DD.md` 中的对应 |
|---|---|
| `signal` | "今日观察"段 |
| `hypothesis` / `attempt` | "今日操作"段 |
| `outcome` | "今日结果"段 |
| `friction` | "今日问题/异常"段 |
| `epoch_boundary` | "今日里程碑/转折"段 |
| `external_candidate` | "今日外部资源"段 |

**轮转策略对齐**：
- OpenClaw：旧 daily note 通过 temporal decay 降权，但保留。
- evolver：`memory_graph.jsonl` 超 100MB gzip 轮转，保留 7 份（`maybe_rotate_memory_graph`，#519）。
- 两者都是**有限保留 + 自动归档**。

---

### 2.3 L3 ── 长期记忆（Persistent Curated Knowledge）

| OpenClaw | evolver.py |
|---|---|
| `MEMORY.md` | `LESSONS_LEARNED.md` |
| 用户偏好、决策、长期事实 | friction points（摩擦点）、教训、规则溯源 |
| YAML frontmatter（隐式） | **YAML frontmatter（显式）** ── 格式近乎完全相同 |
| 手动编辑 + Agent 自动写 | Agent 自动写（`SelfReport.write_lessons()`） |
| 每会话开始注入 prompt | 每周期 collect 阶段注入 ctx（`load_living_memory()`） |
| 超预算时截断注入副本 | 取 top-3 高摩擦类别 + 最近 5 条摩擦点（`high_friction_points` / `recent_friction_points`） |

**`LESSONS_LEARNED.md` 与 `MEMORY.md` 之 YAML frontmatter 直接对照**：

```yaml
# OpenClaw MEMORY.md（典型形态）
---
type: memory
last_updated: "2026-07-20"
tags: [preference, decision]
---
# 用户偏好 TypeScript；项目使用 uv 包管理……

# evolver.py LESSONS_LEARNED.md（实际形态）
---
autopoiesis: true
memory_type: "living"
last_updated: "2026-07-20"
evolution_count: 12
friction_points:
  - id: "f001"
    category: "session_error"
    description: "..."
    resolution: "..."
    rule_id: "session_error_guard"
    timestamp: "2026-07-20T12:34:56+00:00"
---
```

**结构同构一目了然**：两者皆为 `---YAML frontmatter--- + Markdown body`，皆有 `last_updated`，皆以条目化形式组织持久知识。

**L3 周边长期层（与 OpenClaw 多 L3 文件生态对应）**：

| OpenClaw 扩展层 | evolver.py 对应 |
|---|---|
| `USER.md`（用户画像） | `USER.md`（collect.py 直接读取，**文件名相同**） |
| `IDENTITY.md`（Agent 身份） | `personality.json`（严谨度 / 风险容忍度） |
| `SOUL.md`（行为准则） | `autopoiesis_rules.json`（guard_checks） |
| `TOOLS.md`（工具规约） | `genes.json` + `capsules.json`（GEP 资产库） |
| `AGENTS.md`（项目规约） | `AGENTS.md`（项目根，**文件名相同**） |
| `memory/imports/`（外部导入） | `external_candidates.jsonl` + `fetch.py` 拉取的 Hub 资源 |

> **强烈对齐信号**：`USER.md` 与 `AGENTS.md` 之**文件名完全一致**，说明 evolver.py 在文件布局上刻意对齐了 OpenClaw / Codex / Claude Code 生态约定。

---

## 三、辅助机制对应

### 3.1 Pre-compaction Flush（L1 → L2 防丢失）

| OpenClaw | evolver.py |
|---|---|
| 压缩前静默轮次提醒 Agent 保存重要上下文 | 周期 abort 前的 `run_preflight_abort_self_report()` |
| 默认开启，无需配置 | `EVOLVER_AUTOPOIESIS=1` 默认开启 |
| 写入 `memory/YYYY-MM-DD.md` | 写入 `autopoiesis_preflight_abort.json` + `LESSONS_LEARNED.md` |
| 防止 compaction 丢失上下文 | 防止周期中断丢失诊断信号 |
| 触发下一次会话的恢复 | 触发下一周期的 `preflight_abort` 信号注入与 repair bias |

**对齐点**：都是**"工作记忆即将丢失"前的抢救性落盘**，目标完全一致——避免短期状态的不可恢复损失。

---

### 3.2 Dreaming（L2 → L3 后台巩固）

| OpenClaw | evolver.py |
|---|---|
| 后台 cron 定期扫描 L2 | `SelfReport.run()` 在每周期 autopoiesis 阶段触发 |
| 评分（频率/多样性/分数） | 评分（`failure_diagnosis.confidence`、`ViabilityReport`） |
| 通过门槛才晋升 | 仅当 `auto_encode=True` 且 `EVOLVER_AUTOPOIESIS_WRITE=1` 才写盘 |
| 写入 `MEMORY.md` | 写入 `LESSONS_LEARNED.md` + `autopoiesis_rules.json` |
| Diary 供人工审核（`DREAMS.md`） | `self_report.json` + 叙事日志（`evolution_narrative.md`）供人工审核 |
| 候选先暂存到短期 dreaming 存储 | friction 先入 SelfReport 内存累积，周期末一次性 flush |

**双向晋升（evolver 独有的强化对齐）**：
- OpenClaw 的 Dreaming 是单向的（L2 → L3）。
- evolver 之 `memory_bridge.py` 实现**双向**：
  - 正向：`sync_living_friction_to_memory_graph()` 把 L3 摩擦点降级回 L2（作为 friction 事件）。
  - 反向：`capture_memory_graph_bans_as_friction()` 把 L2 统计 ban 升级为 L3 摩擦点。
- 这构成**自反性巩固循环**，比 OpenClaw 单向 Dreaming 更紧密。

---

### 3.3 memory_search（混合检索）

| OpenClaw | evolver.py |
|---|---|
| 向量（embedding）+ BM25 混合 | signal_key（sha256）精确匹配 + 频率统计 |
| 默认 70% 向量 + 30% BM25 | 100% 精确匹配（无语义检索） |
| 两阶段 recall：search → get | 两阶段 recall：`get_memory_advice()` → `build_recall_section()` |
| MMR 多样化 + 时间衰减 | ban 阈值（≥80% 失败率）+ inert ban（连续 8 次零工作） |
| `memory_search` / `memory_get` 工具 | `get_memory_advice()` / `try_read_memory_graph_events()` 函数 |

**对齐点（深层）**：
- 两者都把"检索"作为**派生层**——真值仍在文件中，索引只是加速器。
- 都采用**两阶段 recall**：先粗召回，再精读取。
- 都有**多样化/防退化**机制（MMR ↔ epoch_boundary 重置）。
- 都以**召回结果注入 prompt / ctx** 作为最终消费方式。

**差异**：OpenClaw 用语义嵌入处理"措辞不同的相似回忆"；evolver 用内容哈希处理"同一信号集的精确历史"。这是**场景特化**——evolver 的查询键是程序化生成的 signal set，本就确定性，无需语义模糊匹配。

---

## 四、设计哲学层面的同源（重点）

### 4.1 哲学一：文件即真值源（Files are the Source of Truth）

两者最深的共鸣。OpenClaw 官方文档：

> "Files are the source of truth"——模型只记住写入磁盘的内容，向量索引仅为派生加速层。

evolver.py 之 `AGENTS.md` 同样申明：

> "JSONL 叠加语义"——`genes.jsonl` 条目按 ID 覆盖 `genes.json`；资源完整性通过存于 `asset_id` 中之 `sha256:` 内容哈希验证。

两者皆把**衍生索引**视为可重建的派生数据：
- OpenClaw：`*.sqlite` 索引可由 `openclaw memory index --force` 重建。
- evolver：`memory_graph_state.json` 之 `preferred_by_signal` 可由重放 `memory_graph.jsonl` 重建。

### 4.2 哲学二：分层 + 蒸馏（Tiered & Distilled）

两者都拒绝"一锅粥"式记忆，采取**分层溢流（Tiered Overflow）**模型：

```
原始事件（高吞吐、低信噪比） ──→ 提炼层（低吞吐、高信噪比）
```

- OpenClaw：daily notes（追加）→ `MEMORY.md`（精炼）
- evolver：`memory_graph.jsonl`（追加）→ `LESSONS_LEARNED.md`（精炼）+ `autopoiesis_rules.json`（规则化）

**蒸馏的方向**都是从"信息"到"知识"再到"规则"。

### 4.3 哲学三：Agent 自维护（Agent-maintained）

两者都把记忆维护权交给 Agent 自身：
- OpenClaw：Agent 主动调用文件工具写入；Heartbeat 流程自动整理。
- evolver：`SelfReport.run()` 自动 observe → encode → remember → report；`auto_encode()` 自动把摩擦转为规则。

**关键**：用户**不需要手动管理**每条记忆——这是两者共同的产品哲学。

### 4.4 哲学四：衍生索引（Derivative Indices）

两者都把检索能力构建在文件真值之上：
- OpenClaw：SQLite + sqlite-vec + FTS5 是 Markdown 的衍生索引。
- evolver：`memory_graph_state.json` + `memory_advice` 是 `memory_graph.jsonl` 的衍生索引。

**索引丢失 ≠ 记忆丢失**——两者都遵循此原则。

### 4.5 哲学五：行为影响（Behavioral Influence）

两者的记忆都会**影响 Agent 未来的行为**：
- OpenClaw：MEMORY.md 中的偏好注入 prompt，影响下次回答。
- evolver：L3 friction → `living_memory_score_adjustment()` 直接改写基因选择分数（ban −0.5 / prefer +0.35）。

差异：evolver 的行为影响是**定量的、可执行的**；OpenClaw 是**定性的、prompt 注入的**。这是进化引擎场景的特化。

---

## 五、表层相似（文件与格式层面）

### 5.1 文件布局对照

```
OpenClaw workspace                    evolver.py workspace
~/.openclaw/workspace/                <workspace>/
├── MEMORY.md            ◄──────────► memory/evolution/LESSONS_LEARNED.md
├── USER.md              ◄──────────► USER.md                    ★同名
├── AGENTS.md            ◄──────────► AGENTS.md                  ★同名
├── IDENTITY.md          ◄──────────► personality.json
├── SOUL.md              ◄──────────► autopoiesis_rules.json
├── memory/              ◄──────────► memory/evolution/
│   ├── 2026-07-20.md    ◄──────────► memory_graph.jsonl
│   ├── 2026-07-19.md    ◄──────────► memory_graph.jsonl.<ts>.gz (归档)
│   └── .dreams/         ◄──────────► pending_signals.json
├── DREAMS.md            ◄──────────► evolution_narrative.md
└── agent.sqlite         ◄──────────► memory_graph_state.json
```

### 5.2 格式对照

| 维度 | OpenClaw | evolver.py |
|---|---|---|
| 长期记忆格式 | Markdown + YAML frontmatter | **Markdown + YAML frontmatter** |
| 日志格式 | Markdown（按日切片） | JSONL（按事件切片） |
| 索引格式 | SQLite（B-tree + 向量 + FTS） | JSON（flat state） |
| 时间戳格式 | ISO-8601 | ISO-8601（毫秒精度） |
| 内容寻址 | 文件路径 | `sha256:` 哈希（更强） |
| 配置覆盖 | `agents.defaults.*` | 环境变量（`EVOLVER_*` / `GEP_*`） |

### 5.3 写入触发对照

| 触发场景 | OpenClaw | evolver.py |
|---|---|---|
| 周期/会话开始 | 加载 `MEMORY.md` + 今日/昨日笔记 | collect 阶段加载 `LESSONS_LEARNED.md` |
| 检测到重要信号 | Agent 调用文件工具写 daily note | enrich 阶段 `record_signal_snapshot()` |
| 上下文/周期将终止 | Pre-compaction flush | `run_preflight_abort_self_report()` |
| 周期/会话结束 | Heartbeat 整理 | `SelfReport.run()` + `post_solidify_hooks` |
| 定期巩固 | Dreaming cron | reflection（`should_reflect`） |

---

## 六、结构同构示意图

```
┌─────────────────────────────────────────────────────────────────┐
│            L1 · 工作记忆（进程内、生命周期最短）                    │
│  OpenClaw: ctx window + message deque                            │
│  evolver  : ctx dict + evolution_solidify_state.last_run         │
└─────────────────────────────────────────────────────────────────┘
                            │ Flush / Abort 持久化
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│            L2 · 短期记忆（append-only 时间序列）                   │
│  OpenClaw: memory/YYYY-MM-DD.md  (daily, Markdown)              │
│  evolver  : memory_graph.jsonl    (event, JSONL)                │
│           + events.jsonl / autopoiesis.jsonl                     │
└─────────────────────────────────────────────────────────────────┘
                            │ Dreaming / auto_encode 提升
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│            L3 · 长期记忆（curated、跨周期/会话）                   │
│  OpenClaw: MEMORY.md          (偏好 + 决策 + 事实)               │
│  evolver  : LESSONS_LEARNED.md (friction points + YAML)         │
│           + autopoiesis_rules.json (guard rules)                │
│           + genes.json / capsules.json (GEP 知识库)              │
└─────────────────────────────────────────────────────────────────┘
                            │ memory_search / get_memory_advice 召回
                            ▼
                  注入下一周期/会话的 ctx / prompt
```

**同构性**：层数相同、方向相同（自上而下持久化、自下而上召回）、生命周期梯度相同。

---

## 七、差异点（场景特化，非架构分歧）

为求客观，列出差异。但这些差异皆源自**目标场景**（对话 Agent vs. 进化引擎），**非架构哲学分歧**：

| 差异点 | OpenClaw | evolver.py | 性质 |
|---|---|---|---|
| 检索单元 | 语义（向量） | 精确（内容哈希） | 场景特化：查询键确定性 |
| L2 切片 | 按日 | 按事件 | 场景特化：进化无"日"概念 |
| L3 内容 | 偏好 / 事实 | 摩擦 / 规则 | 场景特化：进化关注失败模式 |
| 行为影响 | prompt 注入（定性） | 分数加权（定量） | 场景特化：进化需可执行决策 |
| 晋升方向 | 单向（L2→L3） | 双向（含 L3→L2 反向同步） | evolver 更强 |
| 多会话隔离 | main / group 独立 | 单实例锁 | evolver 无多会话需求 |
| 嵌入依赖 | 需要 embedding provider | 不需要 | evolver 查询键本就确定性 |

---

## 八、对齐强度总结

> **evolver.py 之记忆子系统，是 OpenClaw 三层记忆模型在进化自修改场景下的同构特化实现。**

- **哲学同源度**：★★★★★（File-first / Tiered / Agent-maintained / 衍生索引 / 行为影响 五项全中）
- **结构同构度**：★★★★☆（L1/L2/L3 + Flush + Dreaming + Search 皆可对位）
- **格式相似度**：★★★★★（YAML frontmatter / Markdown / append-only / 时间戳 一致）
- **机制等价度**：★★★★☆（双向巩固甚至强于 OpenClaw 之单向 Dreaming）
- **差异显著性**：★★☆☆☆（皆为场景特化，非架构本质分歧）

**最终判定**：**两者属同一架构家族**，evolver.py 可视为 OpenClaw 记忆哲学在**自进化引擎**领域的**忠实落地与扩展**。其独有之双向巩固循环、可执行规则层（autopoiesis_rules）、定量行为加权、内容寻址完整性，甚至构成对 OpenClaw 模型的**部分增强**。

---

## 附录 A：核心源文件索引

| 子系统 | evolver.py 源文件 | OpenClaw 对应概念 |
|---|---|---|
| L3 加载 | `src/evolver/gep/living_memory.py` | `MEMORY.md` 加载 |
| L2 事件存储 | `src/evolver/gep/memory_graph.py` | `memory/YYYY-MM-DD.md` + agent.sqlite |
| L2 → L3 桥接 | `src/evolver/gep/memory_bridge.py` | Dreaming + memory flush |
| L3 维护 | `src/evolver/gep/self_report.py` | Heartbeat + Dreaming |
| 自创生编排 | `src/evolver/gep/autopoiesis.py` | （无对应，evolver 独有） |
| 检索 | `get_memory_advice()` in memory_graph.py | `memory_search` 工具 |
| 召回注入 | `build_recall_section()` in cognition.py | memory_search 注入 prompt |
| 信号分类 | `src/evolver/gep/signals.py` | （无对应，对话场景无信号概念） |
| L1 上下文 | `ctx dict` 贯穿 `evolve/pipeline/*.py` | 消息数组贯穿 session |
| 收集阶段 | `src/evolver/evolve/pipeline/collect.py` | session 启动时加载 MEMORY.md |

## 附录 B：术语对照表

| OpenClaw 术语 | evolver.py 对应术语 | 说明 |
|---|---|---|
| Daily Note | memory_graph event | L2 单元 |
| Memory Flush | preflight_abort / SelfReport flush | L1→L2 落盘 |
| Dreaming | auto_encode + memory_bridge | L2→L3 提升 |
| memory_search | get_memory_advice | 检索 API |
| memory_get | try_read_memory_graph_events | 精读取 |
| Compaction | cycle boundary | L1 清理 |
| Bootstrap budget | ctx field cap | L1 预算 |
| MEMORY.md | LESSONS_LEARNED.md | L3 文件 |
| temporal decay | epoch boundary reset | 主动遗忘 |
| wiki plugin | autopoiesis_rules.json | 结构化规则层 |

---

*报告基于 evolver.py `src/evolver/gep/*` 与 `src/evolver/evolve/pipeline/*` 源码、OpenClaw 官方文档（docs.openclaw.ai/zh-CN/concepts/memory）及社区技术解析综合编撰。*
