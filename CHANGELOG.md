# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Changed — round-53：Hub 超时常量实测校准（相位遥测第三笔应用）
- **实测**：端点 curl 三连 404 全部 **1.41~1.50s 稳定**（floor ~1.5s）。
- **`config.py`**：`HUB_SEARCH_TIMEOUT_MS` 8s→**5s**（~3x 余量）、
  `HTTP_TRANSPORT_TIMEOUT_MS` 15s→**10s**（~7x 余量）——旧值只在最坏
  情形起作用（一次 15s 超时+一次重试 = round-45 观测的 15.7s hub 相位
  读数 = round-40/41 tick 超时的放大器），新值把最坏情形减半。常量
  注释内联记录校准依据；消费者只读值零破约；零 env 旋钮。139 相关
  测试全绿。

### Added — round-52：effective-L5 复跑 #4（RSI §6.8，挂钟条款）
- 纪元 E'（rounds 44-51，8/8 零拒绝）——捕获罐连续第二纪元全空
  （维持 2/3 不是退化，捕获本就低频）。E' 独有结构事实：**verdict
  翻转 `unverified` 生产兑现**（round-30 可达性修复从合成预演进入
  生产到达=「修复-等待-兑现」链路第二例；无捕获动作，不计入判据
  (a)）。新观察：**unverified 稳态=「评测者自偏好」反面的定性证据**
  （机器把最终门交还人类）——§2.2 升级辅助论据，不替代捕获要求。
  相位遥测 MCP 路径第二腿激活（engine_log 尾行）——仪器双通道完成。
  复跑 #5 ~round-62 或捕获入账。

### Fixed — round-51：soak 路由白名单存储亲和补全（round-31 互锁完整性收口）
- **`cli.py`**：`_soak_routed_commands` 补 11 个存储/账本亲和命令——
  **写者** `distill`/`fetch`/`sync`/`reuse`/`publish`（裸 CLI 会装基因/
  资源/任务进冻结仓内库=状态分裂；MCP 路径不受累，server 启动即路由）
  + **读者** `asset-log`/`rebuild-views`/`replay`/`exec`/`experiment`/
  `bench`（同 round-49 report 陈旧读数类）。
- 冒烟验证：裸 shell 模拟 distill 前路由 `routed=True`。教训：渐进
  生长的白名单永不完整——修完读者类立即审计整个命令面的写者亲和；
  安全路径（MCP 自动路由）会掩盖不安全路径（裸 CLI）直到有人跑它。

### Fixed — round-49：操作者面陈旧读数修复 + **soak verdict 翻转 `unverified`**
- **里程碑**：cumulative 43——两历史伪杀（round-21/24）全部滑出滚动窗，
  **verdict 由 `false_kill_high` 翻转为 `unverified`**（round-47 预演的
  机器路径生产兑现）。转正唯一剩余阻塞=人工 verified TP（reason 已带
  全路径/行格式/登记条件）。post_cycle 1.662→**0.058s** 归零实证。
- **`ops/soak_env.py`**：`status()` 互锁武装且仓内 shell 时指标改读
  soak 根账本并标注 `metrics_source`（仓内账本冻结 20 轮，冻结数字
  当现况展示误导操作者）；文本行并显 cumulative。
- **`cli.py`**：`report`/`meta-report`/`variants` 三个活账本读者入
  soak 路由白名单（`evolver report` 曾展示 round-29 时代数据；
  gate-report/charter-check 保留显式 `--soak` 双视图）。

### Fixed — round-48：hub_health 状态测试密闭性防线（#37 家族，预防性）
- **威胁**：零隔离 hub 测试跑到 404 路径会把粘性计数写进仓内运行态，
  3 次后 `endpoint_sticky()` 翻真——其它无隔离测试经 hub_client 预检
  fast-fail 而非走各自 mock（#44 soak 路由泄漏同构形状）。
- **`tests/conftest.py`**：autouse `_isolate_hub_endpoint_state`——
  monkeypatch `hub_health.state_path` 指向每测试 tmp，**无条件重定向**
  （条件分支会与测试自身 monkeypatch.setenv 顺序竞争）；两个 hub 测试
  文件的状态种子/断言 API 化。
- **负向验证抓到真泄漏**：全绿后仓内状态文件出现（内容 `not-json`）——
  by-name `import state_path` 绑定原函数对象绕过模块属性补丁；改模块
  引用后零泄漏复验。**教训：monkeypatch 模块属性对 by-name 绑定无效，
  被补丁函数必须经模块引用调用。**

### Changed — round-47：verdict 翻转边界预演 + unverified reason 可操作化
- **预演**：合成「两伪杀滑出」账本过 `summarize_acceptance`——翻转机器
  路径= `unverified` 已验证（非猜测）；cumulative ~43 该判定将成为
  转正唯一阻塞。
- **`acceptance/report.py`**：unverified reason 补全操作者三要素——
  登记全路径（`$EVOLVER_HOME/anchor/gate-verifications.jsonl`）、行
  格式（`{"<event_id>": "confirmed"}`）、**登记条件**（仅当门 shadow
  拒绝了人工复核确认为真回归的事件——登记非真阳性会污染证据）。
  epoch 6 探针不钉 reason 字符串（grep 证实），纯字符串改动锚实弹
  16/16 放行。

### Fixed — round-46：post_cycle 燃烧点收口——hub_health 共享层 + hub_client 预检
- **归因链**：相位遥测三轮纵向 post_cycle 1.334→1.449→1.625s 增长 →
  逐件计时（ATP buyer 0s——consent 禁用排除；`pick_one()` **1.77s**
  坐实——`list_my_tasks` 对死端点 HTTP）。round-45 只护住 hub 相位是
  **覆盖缺口**：hub_client 家族（任务拾取/下单/交付）各烧各的。
- **`gep/hub_health.py`（新）**：粘性端点健康共享层——常量 + 状态
  helpers + `endpoint_sticky()` 谓词（损坏态构造性 fail-open）；
  `pipeline/hub.py` 迁入引用、行为零变化。
- **`atp/hub_client.py`**：`_post`/`_get` 前置预检——sticky 即快速返回
  `hub_endpoint_missing`，**不构造 HTTP 客户端**（测试以构造即 raise
  断言零 HTTP）。计数仍由 hub 相位喂养；拾取同周期运行即受护。
  post_cycle 预期 ~0.1s。

### Fixed — round-45：hub 404 粘性跳过（相位遥测驱动的第一笔偿还）
- **发现升级**：dispatch 时相位再读 hub=**15.714s**（上轮 3.295s——方差
  3.3~15.7s），周期 17.1s 已过 30s MCP 预算一半。**round-40/41 tick
  超时主嫌修正为 hub 相位方差**（round-42 的引擎侧否定是部分否定——
  快 404 日测不出慢 404 日，如实更新）。
- **`evolve/pipeline/hub.py`**：404 是端点事实非瞬态——连续
  `HUB_404_STICKY_THRESHOLD=3` 次后相位级短路 fetch
  （`hub_hit.reason=hub_endpoint_missing` + 重探倒计时），24h TTL 重探；
  成功/非 404 错误诚实重置（网络错误不证明端点不存在）；损坏态
  fail-open。模块常量零 env 旋钮。**关键不变量：不设
  `skip_hub_calls`**——ctx 形状与失败 fetch 完全一致，dispatch 派发
  语义零变化。sticky 后 hub 相位预期 ~0.03s。

### Fixed — round-44：变体档案重派机械腿（round-40 声明纠偏 + DGM 闭环全通）
- **发现**：round-40 声称变体 replay「S29 通道可直接消费」——全仓 grep
  证实 ProposalEdit 仅支持 append/replace/insert_after，**无任何 diff
  语义**；重派腿实为断点。
- **`gep/variant_archive.py`**：`apply_variant`——replay diff 经临时文件
  `git apply --check` 预检后应用；陈旧 diff（树分叉/已落地）净失败、
  工作树零改动；docstring 同轮纠偏。
- **CLI `evolver variants re-dispatch <id>`**：资格核查 advisory（族
  不匹配/被超越仅警告——重派是操作者决策）；应用后提示走冻结路径
  solidify。DGM 闭环（被拒→入档→资格→重派→接受）自此机械全通。
- 附带：**周期相位遥测首读**（round-42 仪器实证）——cycle 4.82s 中
  hub=3.295s（68%，对 404 端点 fetch+重试）、post_cycle=1.449s、余
  七相位各 <25ms；「30s 超时不在引擎侧」有常驻仪器背书。

### Added — round-43：effective-L5 复跑 #3（RSI §6.7，机制密度触发条款）
- 五纪元表新增纪元 E（rounds 36-42，7/7 成功零拒绝）；核心判定
  **「捕获罐全空」**：六项新机制（rounds 37-42）全部自验证通过但零
  真实捕获——机制落地≠有效证据，判据 (a) 不新增，跨纪元证据维持
  2/3 不升 §2.2。(c) 历史最强：锚累计 13/13、T0 跨 7 事件持平、
  「冻结后自审」闭环再添两例。捕获罐悖论与破局路径记档；复跑 #4
  ~round-52 或捕获入账时。

### Added — round-42：周期相位计时遥测（tick 侧观测补齐）
- **`evolve/runner.py`**：九相位（collect→post_cycle）`_timed_phase` 包装
  （monotonic；**失败路径也记录**——最贵的相位常是失败的相位）；
  `swarm_state.json` 增 `last_tick_phase_timings`/`last_tick_total_s`
  （保留存量字段；损坏状态文件静默吞——观察丢失不致命）；engine_log
  尾行打印相位耗时。**观测不执法**：无逻辑门建于计时之上。
- 归因调查记档：round-40/41 两轮 MCP tick 30s 超时的三个引擎侧假设
  全部实测否定（五相位合计 <0.15s / Hub fetch ~1s 快败 / 实例锁
  非阻塞）——主嫌陈旧/孤儿 MCP server 进程（连接归用户处置）。
- Ops：Mimosa 深扫复跑（2026-09-20），25 findings 与 2026-09-17 基线
  **逐条全同**——rounds 35~42 新代码零新增发现，triage 文档持续有效。

### Added — round-41：RSI P1-3 后半场——K=2 候选种群（L2 跃迁主体收口，锚 Epoch 11）
- **`gep/population.py`（新）**：种群搜索作为固化**前置段**——S29 提案在
  fresh worktree（HEAD、无 live 变异 overlay）机械应用 + 级联预选；
  `adjudicate` 全序决胜（accepted>rejected；分降/文件升/索引升，总序
  可复现）；`POPULATION_BUDGET_S=1500s` 模块常量预算守卫（≈round-38
  K=2 投影上限；超时候选标 `budget_skipped` 显式降级，绝不静默截断）。
  **冻结验证者零改动**：胜者仍过 `solidify(proposal=)` 完整路径（T0 门/
  锚照常执法落地）。
- **CLI `evolver solidify --population P1 P2 …`**：N 提案→择优→胜者冻结
  落地→败者以 `population_status` + `sibling_of` 入变体档案（round-40
  档案成为种群败者之家，DGM 同胞谱系）。
- **锚 Epoch 11（第 16 探针 `population-adjudication`）**：冻结择优语义
  ——accepted 击败 rejected、全序决胜可复现、预算跳过可见、无 admissible
  时种群接受自身不落地任何东西。`population.py` 入锚触发面（候选间选择
  权=验证者相邻）；本轮变异自身被 epoch 11 实弹审判 16/16。
- 契约陷阱钉住：`apply_proposal` 成功键=`applied`、失败抛 `ValueError`；
  `_run_validations` 顶层键=`ok`。

### Added — round-40：RSI P1-3 半场——变体档案（DGM 被拒保留 + 重派资格）
- **`gep/variant_archive.py`（新）**：`classify_rejection`（环境性
  timeout/OSError vs 语义性——挂在固化进程内，事件瘦身丢 stderr 前分类）；
  `variant_entry` 携带 unified_diff replay 形状（S29 `swarm_propose` 通道
  可直接消费）；`record_variant` 复活休眠的 `candidates.jsonl` API；
  `re_dispatchable_variants` 纯谓词：环境性 ∧ 信号族头重叠 ∧ 指纹未被
  后续成功超越（DGM「暂弱变体可成垫脚石」的机械边界；语义性拒绝入档
  但不自动可派）。锚拒点同挂（try/except，档案故障不断拒绝流）。
- **CLI `evolver variants [--json] [--signals]`**：列档 + 重派资格标记。
- K=2 双 worktree 种群半场（触冻结验证语义）留下轮配锚 epoch 11。

### Fixed — round-39：g1 幽灵基因 recall 隔离（DEBUG #44 谱系失真最后余波）
- **`gep/cognition.py` + `gep/recall_inject.py`**：recall 提示在库过滤——
  归一化携带 `gene_id`，`search_recalls` 可选 `known_gene_ids` 结构过滤
  （库外基因不可复用故不成提示；无 gene_id 的 legacy 记录透传）；
  `build_recall_section` 接线传入当前库 id 集。幽灵基因（夹具劫持事件的
  谱系残渣）自此不再以「100% 相似度成功经验」喂给选择器。
- 运维：soak memory_graph 剔除 1 行 g1 outcome（派生存储，wiki 清创
  先例；append-only events 账本不改）；evidence_pack 不动（指纹历史
  完整性优先于记分板纯度）。live 即时证伪：tick Recall Hints 全为真实基因。

### Added — round-38：RSI P1-3 前置双口径（library 忠实使用率 + 每次验证成本）
- **`ops/meta_report.py`**：`panel.cost`——计时种群上的中位/均值验证成本、
  拒绝耗时占比、**K=2 投影**（每周期多一个候选的边际成本=中位全量验证价，
  P1-3 种群决策的直接输入）；mean 附离群值诚实注记（pre-round-20 睡眠
  污染不可改史）。
- **`ops/meta_report.py`**：`panel.library.faithful_use`——落地基因检索率
  （被后续周期再选中）与忠实使用率（再选中事件的编辑指纹新颖、非重复已试
  编辑——evidence-pack「勿重复」契约的执行侧度量，RQGM 形状的探测器）。
- CLI `meta-report` 增两行渲染；纯增量，锚探针（epoch 4/10）语义不动。

### Fixed — round-35：环旁路对账揭出三缺陷同轮闭合（DEBUG #44）
- **g1 夹具基因污染活库**：`tests/test_sync.py` 两处 `sync_all(dry_run=False)`
  无隔离，120/115 条夹具基因累积进生产/soak 库——补 `temp_workspace` 隔离
  + conftest 会话级基因库 tripwire + 双库清理。
- **soak 自动路由 env 透传泄漏**：`maybe_route_to_soak` 就地改写 env 后
  `validation_env()` 把引擎路由当操作者意图转发给级联/T0 子进程，worktree
  套件路径解析破——`EVOLVER_SOAK_ROUTED` 哨兵剥离（引擎路由≠操作者意图，
  显式设置照旧透传），锚实弹过。
- **夹具状态劫持固化谱系**：路由子进程把 r1/g1/m1 夹具状态写进 soak 运行态，
  固化消费夹具状态致事件谱系失真（append-only 不改史，DEBUG #44 记档）。

### Added — round-36：effective-L5 复跑 #2（RSI §6.6，零新代码）
- 四纪元表新增纪元 D（含五轮旁路零事件窗口——首个由账本沉默划出的边界）；
  判据 (a) 精化为「环即验证者」；拒绝分型学成熟（B 起精确度 7/8）；
  跨纪元稳定证据 2/3，判定维持「方向性阳性统计未证」。

### Added — round-37：环完整性回执进 charter-check（DEBUG #44 遗留收口）
- **`ops/charter_check.py`**：`loop_integrity`——引擎面提交（`%cI`）vs 最新
  账本事件，drift>3600s 模块常量即 stale；三态不误报；纯观测面不动转正
  合成。`charter_check.py` 入锚触发面（米尺教义），变异自身被锚 15/15
  实弹审判。live 双视图自洽：仓内 stale 112965s / soak ok。

### Added — round-34：RSI P1-4 证据包派发（L2 策略选择权从启发式移交给证据）
- **`gep/evidence_pack.py`（新）**：按信号族（head 归一，与 meta-report 同口径）聚合
  事件谱系，组装**失败侧证据包**——既往干预及其结局（success/failed）、拒绝
  原因、已试编辑指纹（added-lines sha256 短摘要，重复守卫）、家族记分板；
  渲染预算 2400 字符硬编码（零新 env 旋钮），超限时**显式计数省略最旧条目**，
  绝不静默丢证据。
- **提示词接入** (`gep/prompt.py`)：`build_gep_prompt` 增 `evidence_pack` 节，
  置于 `## Context [Execution]` 之后、`## Selected Gene` 之前——**证据先于基因
  建议**，选择器降格为检索增强而非唯一决策路径；新颖族（无既往尝试）不渲染
  该节。
- **周期接线** (`evolve/pipeline/dispatch.py`)：dispatch 从事件谱系（ctx
  `recent_events`，缺省回落 `read_all_events()[-50:]`，与冷却窗口同源）构建
  证据包并注入提示词；结构化包存 `ctx["evidence_pack"]`；组装失败只记
  `evidence_pack_error`，绝不中断 dispatch。
- **干预提议** (`swarm.py` instrument 第二章步骤 2)：宿主执行器获明示决策规则——
  所选基因属「已固化而信号未消」或族内已接受路径持续失败时，优先经
  `swarm_propose`（S29 机械提案，GeneProposal 契约）提交新策略，而非重复已试
  编辑；提案过同一验证门——**策略自主扩权、验收权不动**。
- **锚 epoch 10**：新增第 15 冻结探针 `case-evidence-pack-honesty`（族内失败
  必达执行器 / 预算省略有计数 / 提示词嵌入逐字且可选）；`evidence_pack.py`
  与 `prompt.py` 入 `ANCHOR_TRIGGER_SURFACES`——对执行器隐藏引擎自身失败记录
  即重开 RQGM 自偏好回路，此通道与米尺同级冻结。
- 24 个新用例（pack 构建/渲染/预算、prompt 可选节、dispatch 接线与容错、
  instrument 提示词、锚）；全套 3673 passed；ruff / mypy strict 0 错误。

### Added — round-33：RSI P1-5 基因全生命周期治理（Library Drift 防治）
- **`gep/gene_lifecycle.py`**：`active → under_review → retired` 状态机，判据由
  完整事件谱系纯函数推导（同 meta-report 后代语义：落地事件后 K 轮内触发信号
  是否在失败中复发）。零后效证据（≥3 次可评估落地、0 次解决）→ 复核；复核窗口
  内再试仍零后效 → 退役；复核期内出现解决 → 复活。评估幂等，转移写
  `gene_lifecycle.json` + `gene_lifecycle.jsonl` 审计（actor=engine）。状态文件
  损坏时评估拒绝写入（不覆盖账本），选择器 fail-open（绝不凭空禁选）。
- **选择器强制** (`gep/selector.py`)：retired 基因按禁用处理（含 distilled
  兜底路径）；under_review 基因惩罚 ×0.5 但**仍可选**——复核窗口即可证伪的
  重验试验；`applicability.signal_families` 声明的信号族为硬门（声明而不匹配
  即不检索）。
- **Gene schema** (`gep/schemas/gene.py`)：新增可选 `applicability` 与
  `dependencies` 字段，向后兼容（现有磁盘基因零迁移）。
- **周期钩子** (`evolve/post_cycle.py`)：每周期末由事件账本推导生命周期并持久化，
  转移摘要进 `ctx["gene_lifecycle"]`。
- **CLI**：`evolver gene-lifecycle list|evaluate|reinstate <gene_id>`——退役永不
  自动逆转，仅人类可复活（`reinstated_count` 入审计）。
- **meta-report 增 `library` 面板**：落地基因数、可评估落地数、解决率、
  零后效候选（退役触发面）、生命周期状态计数；`meta-report` 读取状态映射
  传入（报告本身仍零 I/O）。
- **锚 epoch 9**：新增第 14 冻结探针 `case-gene-lifecycle-governance`
  （复核/退役可达、退役不可选、复核可复活、适用性硬门）；`gene_lifecycle.py`
  与 `selector.py` 加入 `ANCHOR_TRIGGER_SURFACES`——选择机制与米尺同级受锚治理。
- 40 个新用例（lifecycle 纯函数/持久化/CLI/选择器/meta 面板/锚）；全套
  **3649 passed**，ruff / mypy strict 0 错误。

### Added — round-32：S29 机械提案通道、P2 数据入口防护、S30.4/30.5 env 退役（演进方案 §11.4）
- **S29 机械提案通道** (`gep/proposal.py`, `gep/solidify.py`, `swarm.py`, `mcp_server.py`)：
  引入 `GeneProposal`、`ProposalEdit` 强契约数据结构，替代非结构化自由编辑与 distill 提取；支持 `exact_match`、`anchor_pattern`、`unified_diff`；`solidify(proposal=...)` 机械应用落地；CLI `--proposal <path>`；MCP 工具 `swarm_propose` 向蜂群宿主开放。
- **P2 数据入口清单与防御** (`gep/llm_template.py`, `gep/feature_flags.py`, `ops/charter_check.py`)：
  声明 9 类半信任自由文本占位符（`FREE_TEXT_PLACEHOLDERS`），在 shell 模板中按占位符身份裸用即拒（消解黑名单军备竞赛），生成 `<stamp>_refused.txt` 审计标记；自动材料化文件通道（`{<name>_file}` 自动材料化 `<stamp>_<name>.txt`）；`enable_llm_template` 注册锚互锁。
- **升锚 Epoch 8** (`assets/anchor/case-data-ingress-guard`)：
  新增第 13 冻结探针，覆盖自由文本身份级裸用拒认、合法文件通道放行、非法注入截断三大安全不变量（13/13 PASS）。
- **S30.4/30.5 env/flag 退役** (`config.py`, `adapters/`, `gep/`, `proxy/`, `webui/`, `atp/`)：
  梳理并折叠 103 个冗余/内部环境变量，全局独立 `EVOLVER_*` 变量从 180 骤降至 77（≤80，`charter-check --soak` 判定 `met=True`）。

### Changed — round-30：验收门退出判据可达性（演进方案 §11.4 P0-1）
- **`gated_cumulative`**：`summarize_acceptance` / `evolver gate-report` 增全时段
  gated 计数；`gated_runs` 仍是滚动窗计数（窗口上限 `GATE_SOAK_MIN_RUNS`，
  饱和后恒为 20），二者并存——饱和不再吞掉阶段进度（DEBUG #41）。
- **`verified_true_positives` / `verified_false_kills`**：人工裁决计数，**全时段**
  不随窗口过期。数据源为仓外只读账本 `$EVOLVER_HOME/anchor/gate-verifications.jsonl`
  （人写、引擎永不写；缺文件与坏行皆跳过），零新增 env 旋钮。
- **判据重排 + 两个新 verdict**：`unverified`（无人工确认真阳性→不得转正）与
  `collecting_verified`（安静期但已获背书）取代结构性不可达的
  `under_intercepting`；校准类判定（`false_kill_high` / `over_intercepting`）
  优先于完备性判定。转正始终由人：`EVOLVER_ACCEPTANCE_SHADOW=0`。
- **锚 epoch 6**：新增探针 `case-gate-verdict-reachability`（累积计数暴露饱和 /
  无指控不给 ready / 确认滑出窗口仍解死锁），全套 11/11 通过。

### Added — soak 外置运行态入口
- **`evolver soak setup|exports|status`**（`ops/soak_env.py`）：在
  `$EVOLVER_HOME/evolver.py-soak/` 建进化目录并写出 `env.sh`，避免 soak
  写回产品仓 `memory/`。`gate-report` 在 `EVOLUTION_DIR` 仍位于 git 工作树内
  时警告（JSON 带 `inside_repo`）。

### Added — S26.5 评估隔离（影子，默认关）
- **`gep/eval_worktree.py`**：`git worktree add --detach` 自 HEAD，只 overlay
  非运行态工作树文件，级联与验收门在该副本上跑；失败回退 live cwd（不挡 soak）。
  `EVOLVER_FF_ENABLE_EVAL_WORKTREE=1` 打开。事件可带 `eval_workspace` 元数据。

### Fixed — instrument prompt 设计审阅：三处事实错误落地修复
- **`failure_mode` 幽灵键**：prompt 两处教宿主读 solidify 返回的
  `failure_mode`，但该键从未出现在工具面。现 `swarm_solidify` 失败时附
  `classify_failure_mode` 结果（`mode`/`reasonClass`/`retryable`——
  `validation_failed` 走真实分类，其余按硬失败）；`next_action` 按
  `retryable` 分派（`swarm_tick` / `stop_and_report`），prompt 同步写明
  retryable 决策语义。
- **mailbox 工具名错误**：prompt 引用 `mailbox_poll`/`mailbox_send`，
  实际注册名 `tool_mailbox_*`——严格调名必败。已改真名并加测试钉住
  （`test_references_real_tool_names`）。
- **「立即行动」与 pending_solidify 自相矛盾**：boot 时有待固化 run 却
  指示宿主先 tick（会覆盖待固化状态）。现按状态分支：pending → 先
  `swarm_solidify`。
- 小项：级联顺序改正（ruff→mypy→pytest）；步骤 1 补
  `next_action=stop_and_report`（`instance_lock_held`）处置。
- 5 个新测试；全量 3508 passed。

## [1.112.0] — 2026-09-05

### Changed — 蜂群闭环稳定化（演进方案.md）

HITL/HOTL 从包装变成互锁；反馈降级机械地强制 repair；固化谱系同时记剧本基因与落地基因；工作流 gate 记下 stdout；运行态踢出产品 git。一天 13 个 minor 的节奏在此刹车。验收门仍 `collecting`（4/20），不转正。

- **HITL**：`parse_hitl_mode`（`ON`/`true`/`1` → on；未知 → on）；`AUTO_HIJACK` 强制开门；`solidify(skip_validation=True)` 自身过审批；无 pending `run_id` 拒绝 skip（消灭 `…:unknown` 粘性键）；状态文件加锁，损坏 fail-closed 拒绝；`list_pending` 惰性过期 TTL。
- **HOTL**：`_run_single_cycle` 尊重 pause；select 之后、dispatch 之前按基因 id 否决（不再先 `print(prompt)` 再扣发）；solidify 按基因 id 再挡；`swarm_tick` 取实例锁；监督 JSON 损坏视为暂停；绊线跳过坏行；过短/过泛 veto 模式拒绝；CLI `supervise veto --note` 真正传入。
- **MCP**：`AUTO_HIJACK` 下拒绝 host 转达的 approve / resume / unveto；`approval_resolve` / `supervise` / `workflow_act` 标 destructiveHint；`evolver://instrument-prompt` 只渲染文本，不 `swarm_boot`。
- **反馈**：`swarm_feedback:degraded` 或自适应 `repair_bias` → `autopoiesis_repair_bias` / `force_category=repair`（与 autopoiesis 摩擦同路）。
- **谱系**：distill 把落地 gene id 写入 solidify state；事件带 `landed_gene_id`；提交说明与冷却窗口罚落地基因。
- **工作流 gate**：合并 stdout+stderr 尾、`cwd=workspace`、尊重 `timeout_ms`；嵌套 `agent`/`approval` 传播 park；repair/innovate 模板写真话（批准 ≠ 自动 solidify）。
- **卫生**：gitignore `memory/` 运行文件与 `evolver/.config/`（保留 `LESSONS_LEARNED.md`）；CHANGELOG 只留一个 Unreleased；`check_changelog.py` 拒绝多个。
- **杂项**：`EVOLVER_SKILL_ROOTS` 按 `os.pathsep` 分割；CLI distill 零资产给出 hint。

### Upgrade notes
- **`EVOLVER_HITL_MODE` 未知取值现 fail-closed 为 `on`**。`ON`/`true`/`1`/`yes` 打开；
  `off`/`false`/`0`/`no` 关闭。若曾设 `disabled`、`ENABLED` 或其它非枚举串，升级后
  会开始拦截 `skip_validation`——本意关闭请显式写成 `off`。
- round-1~5 历史事件只有剧本 `gene_id`，冷却窗口对旧事件会失效一轮，属预期，
  不必回填。新固化同时记 `landed_gene_id`。

### Docs — DEBUG.md 修复经验簿
- 新增 **`DEBUG.md`**：dogfood 五轮、补测与 v1.112 审阅之 13 个 bug 全录
  （症状/根因/修复/可迁移经验四段式）+ 方法论沉淀（覆盖审计先行、实证
  闭环、静默降级头号嫌疑、真仓即试验场）；AGENTS.md 坑阱篇置顶链接。
- 顺手修复 README.md 文档区残留断链（`设计方案.md` 已于 c195b82 删除）
  与过期弧线注记（v1.98–v1.105 → v1.98–v1.111）。

### Added — 最近一周 API 表面补测（v1.98–v1.111，25 个新用例）
- **`tests/test_recent_api_surface.py`**：覆盖审计驱动（`--cov` 找冷分支），
  补齐六块——
  - `default_cascade_runner` **真实子进程执行路径**（此前只测空命令分支）：
    全过/失败上报 stderr/二进制缺失 OSError→-1/超时 TimeoutExpired→-1/
    gate 步骤端到端；
  - `WorkflowEngine` 边界动词：reject 于终态、cancel 于终态幂等、
    resume 于 waiting_agent 复停、load 缺失 LookupError、load_spec 非映射拒绝；
  - `swarm_skills` scan/list/未知动作；`swarm_workflow_act` cancel/resume/
    未知动作/**失败任务错误面**；`swarm_workflow_status` awaiting 分支；
    spec 文件损坏 workflow_error；
  - `hitl` TTL 过期后**重复申请**的惰性过期+fail-safe 拒绝（防审批购物）
    与 `list_recent`；`feedback.load_recent_feedback` 冷日志与持久读取；
  - CLI 新动词：`skills scan/list`、`gate-report --json`、`workflow templates`。
- 模块覆盖率：workflow 88%→**94%**、swarm 82%→**89%**（hitl/feedback 补边界）。

### Fixed — 伴随补测发现的引擎语义缺口
- **`complete_agent` 无视失败契约**：结果为 `{"ok": False}` 时工作流照常推进
  ——CLI `--fail` 与 `swarm_workflow_act complete` 的失败语义形同虚设。现
  dict 结果携带 `ok: False` 即失败该 run（WAL 记 `agent_failed`），与
  approval/gate 的失败语义对齐。

### Docs — 全量文档对齐 v1.111.0 实现现状
- **README.md**：实现状态段 1.105.0→1.111.0（补 v1.106–v1.111 弧线：自适应变异、
  验收门 soak、dogfood 五轮、工作流引擎；新增工作流引擎/验收门两行）；
  环境变量表补 17 个 v1.99+ 变量（HITL/HOTL/反馈/技能/门/冷却/Hub 重试/
  AUTO_HIJACK）；测试计数 3400+→3455+。
- **README.zh.md**：新增「MCP 蜂群进化」「进化工作流」「技能生态桥」三章节
  （原零覆盖）；实现状态自 2026-06-11（1250+ 测试）重写至 v1.111.0；
  环境变量表/示例表同步。
- **README.ja-JP.md / README.ko-KR.md**：主機能补蜂群/工作流条目；实现状态
  1.94.0→1.111.0；示例表补 swarm-quickstart；环境变量表补新变量。
- **examples/README.md**：Core Workflows 补 swarm-quickstart；新增「Evolution
  Workflows」小节（模板即教程）；命令速查补 mcp/workflow/gate-report/
  hitl/supervise/skills。
- **docs/env-registry.md**：`scripts/env_inventory.py` 再生成（234→252 变量）。
- **TODO.md**：指针刷新（1.94.0/3002 测试 → 1.111.0/3455 测试 + dogfood
  gated_runs=4 + EvoX 收割完毕）。
- **断链修复**：`演进方案.md` 已于 c195b82 删除但 12 处引用残留——统一改指
  尚存之 `演进方案_wikiskill对照版.md`（README×4 语言、TODO、
  SELF_HARNESS_CHECKPOINT）。

## [1.111.0] — 2026-09-04

### Added — dogfood round-5：已应用基因冷却（选择器效率，gated_runs 3→4）
- **观察**：round-3/4 的 tick 反复选中早已落地的基因（同信号仍在语料、
  同基因仍最佳匹配）——每次重派都是浪费的周期。选择器此前对「近期已
  成功固化」零感知。
- **修复**：`select_gene` 对近窗内成功固化过的基因施加**惩罚（×0.25，
  非禁选）**——并列时新候选胜出、唯一匹配仍可选；窗口只计带 outcome
  的 mutation 事件（簿记噪音不稀释）；事件尾加载独立于
  `enable_event_history`（该 flag 默认关，曾令冷却静默失效——本根因
  由 gate 前实证发现）。实证：同信号下选择从已落地的
  `gene_hub_retry_helper` 切换到从未应用的 `gene_degraded_local_dispatch`。
- 新配置：`EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS`（默认 5）/
  `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY`（默认 0.25）；8 个新测试；
  新基因 `gene_applied_cooldown`；引擎提交 1bc35c3。
- 工作流 gate 首次逮住真实违规（测试文件 RUF005）——innovate 模板
  `on_fail: skip` 容忍并如实记录，修复后经 solidify 权威级联全绿。

## [1.110.1] — 2026-09-04

### Fixed — dogfood round-4（repair 工作流首个实战周期，gated_runs 2→3）
- **`swarm_distill` 静默零产出**：非空响应但零资产提取时（纯文本摘要、
  无 ```json 块），返回值只有 `genes: 0` 且无任何指引——宿主无从自纠。
  现附 `hint`（期望的资产块形状 + `Gene.category` 合法枚举）并把
  `next_action` 置为 `resubmit_with_asset_blocks`；格式损坏但存在块的场景
  validation errors 与 hint 双信号并列。3 个新测试钉住（hint 触发/valid
  无 hint/坏类别 hint+errors）。
- 本轮为 **repair 模板工作流首个实战周期**（mutator → gate 真实级联
  三阶段绿 → 审批），与 round-3 的 innovate 模板互补；引擎提交 d68a7fc，
  爆炸半径恰 2 文件。新基因 `gene_distill_format_hint` 入库。

## [1.110.0] — 2026-09-04

### Added — EvoX 工作流收割：协作即数据（YAML 工作流 + 角色节点 + 级联门）
- **YAML↔DSL**：工作流 spec 支持 YAML 载入/导出（`load_spec` 按后缀分派、
  `dump_spec_yaml` 往返）——工作流成为可 diff、可进化的数据资产；`pyyaml`
  转正式声明依赖。
- **协作模式 = 节点**：`agent`/`approval` 步骤携带 `role`/`instruction`/
  `risk_reason` 元数据，`awaiting_agent()` / `awaiting_approval()` 向宿主
  执行器与人类审批者声明「现在该做什么」；WAL 等待事件记录角色。
- **`gate` 步骤**：引擎侧直跑 fitness 级联（ruff→mypy→pytest，与 solidify
  同源命令规格）；失败默认终结工作流，`on_fail: skip` 容忍并记录判定。
- **捆绑模板**：`repair`（摩擦修复回路：agent 变异 → 级联门 → 发布审批）
  与 `innovate`（探索回路：弱信号创新 → 级联门容忍失败 → 去留审批）；
  `evolver workflow templates` 列出。
- **MCP 三工具**：`swarm_workflow_run`（文件或模板启动）、
  `swarm_workflow_act`（approve/reject/complete/resume/cancel）、
  `swarm_workflow_status`（全量状态 + 宿主待办）。CLI `workflow` 增
  `templates`/`awaiting`/`complete` 动词，`run` 收 YAML 与 `--template`。

> 设计注：未另造 DAG 引擎——Sprint 24.10 既有持久化引擎（WAL + 快照 +
> 重试退避）已是外部驱动状态机；EvoX 收割以四处增量（YAML/角色/门/模板）
> 落于其上，`agent` 步骤等待面即蜂群宿主接口。

## [1.109.0] — 2026-09-04

### Added — dogfood round-2：验收门开始积累真实数据（首个 gated run）
- 级联修复后重放 round-2 变异并 `solidify` 成功：`gene_hub_retry_helper`
  （`_post_with_retry` 共享重试策略，fetch_tasks 与 send_heartbeat 统一走
  同一指数退避；None timeout 回退 `HTTP_TRANSPORT_TIMEOUT_MS`）——引擎提交
  a576564，`ValidationReport` 三阶段 overall_ok=True（216s），爆炸半径恰为
  8 文件（运行态过滤持续生效）。
- **验收门首个 gated run 落账**：`gate-report` gated_runs 0 → 1，
  `acceptance_result` 随事件持久化，verdict 诚实停在 collecting（< 20）；
  转正开关仍由人类掌握（`EVOLVER_ACCEPTANCE_SHADOW=0`）。

### Fixed — round-2 级联真实执行后暴露的存量闸门债
- **15 个跨平台 mypy 错误清偿**（此前级联从未真正跑过 mypy stage，v1.108
  venv 修复后才暴露）：winreg/windll/creationflags/CTRL_BREAK_EVENT 等
  Windows-only 属性统一改 `getattr(module, name, default)` 惯用法（运行时
  行为不变）；`os.getloadavg` 改 getattr 探测路由 fallback；删除 4 处已
  漂移的 unused-ignore（sandbox_executor×3、winreg import×1）。
- **测试隔离缺陷（dogfood 第 4 缺陷）**：`test_repair_loop_circuit_breaker_
  empty` 直读宿主仓库真实 `events.jsonl`，round-2 的 repair+failed 真实
  事件使其宿主相关地失败——补 `GEP_ASSETS_DIR` 隔离。

## [1.108.0] — 2026-09-04

### Added — dogfood round-1：蜂群在真实仓库完成首轮自主进化
- 首次以宿主执行器身份跑通全闭环：`swarm_hook_event`（真实错误信号）→
  `swarm_tick`（真实 21KB GEP dispatch，选中 gene_gep_repair_from_errors，
  信号聚焦活记忆摩擦点 f001 hub_offline）→ 最小忠实变异 → `swarm_distill`
  （新基因 gene_hub_fetch_resilience 入库）→ `swarm_solidify`（引擎提交
  cb1c1d4）→ `swarm_feedback`。
- 变异本体：Hub `fetch_tasks` 增加一次指数退避重试（f001「retry with hub
  fetch resilience」）——`EVOLVER_HUB_FETCH_RETRIES`（默认 1）/
  `EVOLVER_HUB_FETCH_RETRY_BACKOFF_MS`（500ms）；三个新测试钉住
  重试后成功/禁用回退/失败透传。

### Fixed — dogfood round-1 暴露的两个引擎缺陷
- **运行时状态混入变异提交**：守护实时写的 memory/、.evolver/、
  evolver/.config/ 文件被 `_commit_mutation` 一起提交、把爆炸半径从 3 文件
  虚增至 42——新增 `_is_runtime_state` 过滤（提交目标与爆炸半径一致排除）。
- **裸 venv python 下级联全跳过**：PATH 无 ruff/mypy/pytest → 全部 stage
  skip → unvalidated success（本轮未积累 gated run 的直接原因）——
  `get_fitness_cascade_commands` 回退解析 `<sys.executable 目录>/工具`，
  子进程级测试复现真实场景（清洗 PATH 后三阶段全部解析为绝对路径）。

## [1.107.0] — 2026-09-04

### Added — acceptance-gate soak report（验收门 soak 报告与转正判定）
- `evolver gate-report [--json]`：聚合 shadow 事件为 interception/false-kill
  指标（既有 `summarize_acceptance` 增加时间窗），并给出**转正判定**
  （`gate_soak_recommendation`）：collecting（样本 < `EVOLVER_GATE_SOAK_MIN_RUNS`，
  默认 20）/ ready（interception 落 [0.05, 0.5] 且 false_kill ≤ 0.1）/
  over_intercepting / under_intercepting / false_kill_high。转正开关
  （`EVOLVER_ACCEPTANCE_SHADOW=0`）仍由人类决定——报告只回答"数据是否支持"。
- 真实复盘（本仓库）：gated_runs = 0——守护周期从未走到被验收门打分的
  solidify，soak 样本为零，verdict = collecting；转正前需先积累真实
  gated runs（如经蜂群跑若干轮真实变异）。

## [1.106.0] — 2026-09-04

### Added — feedback-adaptive mutation bias（EvoX 自适应变异率收割）
- `gep/adaptive.py`: 统一评估反馈 E 通道（v1.99）现在直接调制策略权重——
  降级连击（≥3 连续 degraded）→ repair 偏置；收敛平台（stddev < 0.01 且
  均值 ≥ 阈值，EvoX AFlow 收敛判据）→ novelty 枢转；混合/样本不足保持
  中性。权重重归一化并 clamp，verdict 随 `policy["adaptive"]` 进入 GEP
  提示词的 strategy_policy 行与周期事件。`compute_adaptive_strategy_policy`
  接线；`swarm_status` 暴露 `feedback.mutation_bias`。反馈日志为空即 no-op
  （CLI/守护用户不受影响）。`EVOLVER_ADAPTIVE_MUTATION`（默认 on）与
  `EVOLVER_ADAPTIVE_MUTATION_SHIFT`（默认 0.2）可调。

## [1.105.0] — 2026-09-04

### Added — full-coverage swarm E2E（全覆盖 E2E + 真实 LLM 进环）
- **Tier A（始终运行）**: `tests/e2e/test_swarm_full_e2e.py` 经真实 stdio 子进程走遍整个 MCP 表面——全部 swarm/经典工具、四只 `evolver://*` 资源、`evolver_swarm` prompt、auto-hijack 指令变体、HITL 自动批准 + HOTL pause/direct/veto 线上流。
- **Tier B（`-m llm`，需 `DEEPSEEK_API_KEY`）**: **deepseek-v4-flash 真实扮演宿主执行器**——tick → LLM 执行真实 GEP dispatch 提示词 → distill → feedback → 二次 tick。LLM 客户端只存在于测试 harness，引擎保持零 LLM 依赖。

### Fixed
- MCP 工具结果必须优先读 `structuredContent`（规范要求顶层为对象，SDK 将非 dict 返回包为 `{"result": ...}`；`content[].text` 对 list 只含首元素）——已文档化并应用于全部 MCP 测试客户端。

## [1.104.0] — 2026-09-04

### Added — skill ecosystem bridge（技能生态桥，EvoX SkillRegistry 概念收割）
- `gep/skill_assets.py`: 多根优先发现（工作区 `.agents`/`.claude` skills > 用户 `~/.agents`/`~/.zcode`/`~/.claude` skills > 内置）+ 同名遮蔽；同步为 `gene_distilled_s2g-*` 基因入库，使宿主生态技能参与信号匹配。CLI `evolver skills list|scan|sync`；MCP `swarm_skills`；`EVOLVER_SKILL_ROOTS` 覆盖根（顺序即优先级）。

### Fixed
- 技能基因原用 skill2gep 本地哈希公式，被资产库内容哈希校验静默丢弃——同步时改用权威公式重算 `asset_id`。

## [1.103.0] — 2026-09-04

### Added — MCP surface completion + protocol E2E
- MCP resources: `evolver://status` / `evolver://instrument-prompt` / `evolver://dispatch/last` / `evolver://events/recent`。
- 工具注解: readOnlyHint（只读工具）/ destructiveHint（`swarm_solidify`）。
- `tests/test_mcp_protocol.py`: 真实子进程 stdio JSON-RPC 协议 E2E。

### Fixed — 测试套件首次全绿（3377 通过）
- `feature_flags`: 源码级大小写不敏感 env 回退（POSIX 上小写 `EVOLVER_FF_enable_xxx` 曾被静默忽略）。
- Bedrock 流测试: dev 组补 boto3。Solo CLI 测试: 接受 POSIX max-cycles 交接退出码；替代进程指向 no-op 杜绝孤儿重生链。macOS `/var → /private/var` 符号链接断言改比较 resolve 路径。self-repair 测试: `git checkout -B`（defaultBranch=main 下幂等）。

## [1.102.0] — 2026-09-04

### Added — hooks integration for MCP hosts（双轨）
- `swarm_hooks`（status/install/uninstall，包装 setup-hooks）供支持文件钩子的宿主；`swarm_hook_event` 进程内桥（session_start/session_end/signal_detect → 共享信号检测器 → pending_signals）供 MCP-only 宿主。instrument prompt 第三章（Hooks 集成）指导择轨。README 增 MCP 配置指南（ZCode / Claude Code / Cursor）。

## [1.101.0] — 2026-09-04

### Added — HOTL human-on-the-loop supervision（人在环上监督层）
- `gep/supervision.py`: running/paused 状态机（优雅排水）；veto 子串模式（tick 命中扣发提示词 + solidify 阻断，纵深防御）；directive 转向指令注入下轮信号；降级连击绊线自动暂停（`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`）。CLI `evolver supervise`；MCP `swarm_supervise`。与 HITL 正交互补，补全自治光谱。

## [1.100.0] — 2026-09-04

### Added — HITL fail-safe approval gate（EvoX HITLManager 概念收割）
- `gep/hitl.py`: `swarm_solidify(skip_validation=true)` 过审批门——`EVOLVER_HITL_MODE=on` 阻塞待 `evolver hitl approve`，TTL 超时 fail-safe 拒绝，按 subject 幂等（杜绝 approval-shopping），off 模式仍全程审计。CLI `evolver hitl list|approve|reject`；MCP `swarm_approvals`/`swarm_approval_resolve`。
- 反馈稳定性观察面（EvoX 双收敛判据）: `swarm_status` 报告近期反馈分数 stddev。

## [1.99.0] — 2026-09-04

### Added — unified evaluation feedback E（统一评估信号，EvoX 概念收割）
- `gep/feedback.py`: `swarm_feedback` 上报 `primary_score`/`metrics`/`textual_gradient` 三分离；降级报告注入 `swarm_feedback:degraded` + 梯度信号键走 pending_signals 通道（与 autopoiesis 摩擦同路）驱动下轮修复偏置；全量记 `feedback.jsonl`。

## [1.98.0] — 2026-09-03

### Added — swarm evolution via MCP host-agent takeover（蜂群宿主接管，关闭"半开环执行断层"）
- 引擎不自建 LLM API 调度：经 stdio MCP 连入的宿主 Agent 即执行器。注入方案概念收割自 nanoclaw.go（instructions + boot 工具）并叠加正式 MCP prompt 作为显式 instrument。
- `evolver.swarm`: 接管提示词 + 传输无关闭环工具（boot/tick/distill/solidify/report/status）；引擎 stdout 全捕获（stdio MCP 独占 stdout）；`swarm_state.json` tick 台账；preflight abort / user-lock 冲突优雅返回 stop_and_report。
- `evolver.mcp_server`: `evolver_swarm` prompt + swarm 工具面；`EVOLVER_SWARM_AUTO_HIJACK=1` 无人值守接管。dispatch 将组好的 GEP 提示词存入 ctx 供进程内调用方。

### Changed — S30 dependency layering（依赖分层治理）
- fastapi/uvicorn 移入可选 `evolver[server]` extra；server 命令缺依赖快速失败并提示安装；新增依赖分层守护测试。

### Fixed
- 会话级 `EVOLVE_LOAD_MAX` 屏蔽环境负载，根治全周期测试的环境性抖动。

## [1.97.0] — 2026-09-02

### Added — handover items closed (演进方案_wikiskill对照版.md §8 移交余项)
- **S27.2 patterns projection**: new `gep/wiki_projection.py` — regenerates `wiki/patterns/{friction.md, preferred-genes.md}` as deterministic human-readable projections of machine-layer state (LESSONS_LEARNED friction points, memory_graph `preferred_by_signal`), rewrites `wiki/index.md`, audit-commits to the wiki repo. Pages carry no timestamps (git log is the provenance) so projections are byte-idempotent. Trigger: `evolver report`.
- **S27.4 run report**: new `gep/report.py` + `evolver report [--output] [--limit] [--no-project]` — per-cycle verdict counts (success / failed / unvalidated / fitness-gate verdicts / acceptance rejections), the r_best ledger per measurement domain, wiki layer counts, and a **negative-results section rendered as-is** (most recent first; empty window says so instead of claiming success). Runs the patterns projection first unless `--no-project`.
- **S28.2 launch-failure signalization**: `launch_failure_detected` joins `OPPORTUNITY_SIGNALS` + new `signals.count_launch_failures(rows)`; `evolver trajectory` export counts launch failures in the exported rows and queues `launch_failure_detected` via the existing pending-signals pipe — the next cycle's signals phase consumes it automatically ("couldn't start" ≠ "didn't work", wikiskill Run-4 lesson, now wired end-to-end).

### Fixed
- **bench pytest-fast false failure (审阅勘误 #7)**: the health task's hardcoded 300s timeout sat BELOW the real not-slow suite duration (~310s) → `TimeoutExpired` → permanent R=0.5 on a green repo. The bench timeout now reuses the cascade's `FITNESS_PYTEST_TIMEOUT_MS` (600s, env-overridable) — one source of truth for the same suite; regression test pins bench ceiling == cascade ceiling. Post-fix `evolver bench run` measures R=1.0.

## [1.96.0] — 2026-09-01

### Changed — Sprint 26: quantitative fitness promoted to DEFAULT path (演进方案_wikiskill对照版.md §S26; mirrors the wikiskill gating loop)

- **Fitness cascade ON by default** (`enable_fitness_cascade: true`): every solidify now runs the engine-owned validation cascade (ruff → mypy → pytest, short-circuit, per-stage timeouts). Commands whose executable is missing from PATH are skipped with a warning, so non-Python workspaces degrade to the legacy `mutation.validation` path instead of failing every cycle (`solidify.get_fitness_cascade_commands`).
- **Honest outcome scores**: a validated success lands the MEASURED cascade score; an unvalidated success (skip_validation / empty cascade) lands `score: null` + `unvalidated: true` instead of a fabricated `1.0` (`solidify.py` — closes the §13 audit's headline gap).
- **Failure events ON by default** (`enable_failure_events: true`): every terminal solidify failure lands an EvolutionEvent — silence is not an honest outcome.
- **Acceptance gate ON by default, shadow mode first** (`enable_acceptance_gate: true` + `EVOLVER_ACCEPTANCE_SHADOW=true`): T0 verdicts are computed and recorded on events (shadow markers) but never enforced during the soak window. Enforcement: `EVOLVER_ACCEPTANCE_SHADOW=0`.
- **Strict-improvement fitness gate (r_best ledger)**: new `gep/fitness_state.py` (`evolution_fitness_state.json`: baseline / r_best / decision history). Every measured solidify score is compared against r_best (`R > R_best`, strictly greater — first measurement establishes the baseline, like the wikiskill establishing run). Shadow period: verdicts land on events as `fitness_gate`; enforcement (rollback of `no_improvement` mutations) via `EVOLVER_FITNESS_GATE_ENFORCE=1`. Unmeasured (None) scores never touch the ledger.
- **Wiki knowledge layer (S27)**: new `gep/wiki.py` — `<EVOLUTION_DIR>/wiki/` with its OWN git repository (audit commits only, never rolled back): `README.md` / `index.md` / `log.md` (one line per accepted mutation) / `skill-impact.md` (full record of every rejected / non-improving mutation) / `patterns/`. Solidify projects every terminal outcome into the wiki: accepted → log; validation-failure / novelty-duplicate / acceptance-rejection / fitness-enforcement-rejection / shadow no_improvement → skill-impact entries. **Asymmetric rollback verified by tests**: workspace `stash` and even `reset --hard` leave the wiki byte-identical (skills are hypotheses, the wiki is evidence). **Rejection memory is main-path**: every GEP prompt now carries a `## Wiki Impact` block listing recent rejection headings ("do NOT repeat these approaches") — the wikiskill skill-impact contract, wired by default.
- **Cascade failures carry lineage**: `_handle_cascade_validation_failure` events now include GEPA lineage fields (parent_event_id), matching the novelty-rejection path.
- **Repo dogfood / state hygiene**: `evolver/.config/disk_flags.json` untracked and gitignored — it is runtime hot-reload state (auto-seeded from `DEFAULT_FLAGS` on first run), not source; tracking it made every test run dirty the worktree (first slice of 演进方案 S30.8 "runtime state out of the repo").
- Test infrastructure: `tests/conftest.py` swaps in a workspace-neutral cascade command set globally (sandboxed workspaces have no src/tests for host tooling); legacy-path tests opt out via `set_flag("enable_fitness_cascade", False)`.

### Added
- **Built-in deterministic benchmark pack (S26.1 completion)**: `bench/builtin_pack.py` + `evolver bench init [dir]` — 12 tasks across five families (spec-literal / extract / code / json / traps) aimed at classic agent failure modes; byte-identical across generations; the double-exclusion trap asserts at GENERATION time that its clauses do not compensate (wikiskill bench discipline). `load_pack` accepts both the wrapped `{"pack_version","tasks"}` file and bare wikiskill lists. Self-consistency tests now pin ALL FOUR graders (exact / contains / json_field / code_stdout), closing review-erratum item 5.
- **Launch-failure honesty (S28.2)**: `Trajectory.activity` derived field (`launch_failure` / `active`, `__post_init__` from `stats.tool_call_count`) — a zero-tool-call session is exported as a launch failure, NOT behavioral evidence (wikiskill Run-4 lesson, architecture-level). The classification rides every exported JSONL row for downstream distill/signal consumers.
- **Paired statistical comparison (S30)**: new `bench/compare.py` + `evolver bench compare <a.json> <b.json> [--alpha]` — answers "did the mutation actually help?" with an exact two-sided binomial test on discordant pairs (hand-written, stdlib-only; known-value contract `(10,0) → 2/2**10`). `bench run --output` persists per-task results as the comparison input. A verdict requires BOTH the correct direction AND p ≤ alpha — small samples honestly report `no_significant_difference` (3:0 sweeps do NOT reach significance, and the tests pin that). Task-set mismatch is a hard error: comparing different task sets is meaningless.
- **Gene proposals — mechanical mutation application (S29)**: new `gep/proposal.py`. Agents submit a `GeneProposal` JSON (`patch` / `create` / `no_action` with `append` / `replace` / `insert_after` edits); the engine applies it mechanically with hard validation: **anchor text must match exactly and uniquely** (a hallucinated or ambiguous anchor rejects the WHOLE proposal — validate-all-first, no partial application), file paths must stay inside the workspace and out of forbidden dirs (.git/.venv/node_modules/.evolver), and `no_action` is a first-class outcome. CLI: `evolver apply-proposal <file>`; flow: apply → `evolver solidify` (cascade + gates). Same-batch same-file edits compose sequentially and fail loudly if a batch disturbs its own anchor.
- **Immutable evidence layer (S28.1)**: new `gep/evidence.py` — `<GEP_ASSETS_DIR>/evidence/<run_id>/` keeps the FULL scene per solidify run (event + validation results + fitness verdict + gate). Architecture-level immutability: writing the same evidence file twice raises `FileExistsError` — no silent history rewrite; replays reproduce byte-identical files. Wired on the success and cascade-failure paths (best-effort).
- **Environment variable registry (S25.5)**: `scripts/env_inventory.py` (pure stdlib AST scan) + `docs/env-registry.md` — 234 unique variables audited with their read mechanisms; the pruning baseline for S30.4 governance.
- **`evolver bench` subsystem (S26.1)**: `src/evolver/bench/` — the measurement surface of the fitness revolution. `bench list` / `bench run [--no-record]`: weighted built-in health tasks (ruff / mypy / pytest-fast; PATH-missing tasks skip like the cascade) scored into the r_best ledger (`record_measurement(source="bench")`). Task-pack library in wikiskill task format (`{id, split, prompt, sandbox, grader}`): validation, sandbox materialization with force-cleanup (phantom-scoring defense), and four deterministic graders (`exact` / `contains` / `json_field` / `code_stdout`, all 0.0/1.0, never crash, missing deliverable = 0).
- **Semi-automatic pack executor (S26.1c)**: `bench prompt <id> --pack tasks.json` materializes the sandbox (force) and prints the agent prompt (absolute WORKING DIRECTORY, no-outside-exploration rule — the engine never runs an agent, the prompt is the interface); `bench grade <id> --pack` scores the deliverable (single score, never moves r_best); `bench run --pack --split val` aggregates a split into one R measurement. **S26.4 split discipline**: gate ONLY on val — train splits are excluded from gate R by construction; pending sandboxes (agent hasn't run) are reported and excluded, and an empty graded set records nothing.
- `tests/gep/test_sprint26_promotion.py`: promotion contract (default flags, shadow default, PATH filtering, measured vs unvalidated scores, graded failure + lineage).
- `演进方案_wikiskill对照版.md`: evolution plan audited against the wikiskill reference implementation (arXiv:2608.27454) — S25–S30 roadmap.

### Fixed — dual-axis review remediation (2026-09-01)
- **boto3 mis-removal (P0)**: the S25.4 audit's "0 references" claim was wrong (scan depth missed 3 lazy imports in `proxy/router/messages_route.py`); boto3 restored into the optional `[bedrock]` extra — the Bedrock relay's own not-installed fallback made it optional by design. Audit doc corrected.
- **r_best domain mixing**: the fitness ledger is now domain-separated (`cascade` / `bench:health` / `bench:pack:<split>` routed from the measurement source) — a cascade 1.0 can no longer permanently lock out bench improvements; legacy top-level state auto-migrates to the `cascade` domain; cross-domain isolation is test-pinned.
- **wiki parent-tracking hole**: `wiki.ensure()` now idempotently appends the wiki path to the parent repo's `.gitignore` — a parent auto-commit + `reset --hard` can no longer roll back "never-rolled-back" knowledge (new scenario test: parent commits everything, hard-resets, wiki survives and was never tracked).
- **S26.3 acceptance #2**: new end-to-end harmful-mutation test (proposal injects a harmful edit → cascade vetoes → working tree rolled back → failed event + wiki evidence land).
- **Review cleanup**: shared `_failure_event()` builder deduplicates the four rejection-event shapes in solidify; `_now_iso_ms()` helper; `Trajectory.activity` typed `Literal`; dead branch removed from `env_inventory.py`; `baseline_snapshot.py` parses the version with `tomllib`; new tests use `set_flag(..., persist=False)` (no more disk-flag pollution); new modules annotated "No Node.js equivalent" per the docstring convention.

## [1.95.0] — 2026-08-15

### Added — Sprint 22/23: methodology hardening (演进方案.md §13; all behind feature flags, default OFF; flag-off behavior byte-identical with 1.94.0)

- **Open-loop closures (22.1)**: `enable_event_history` (EvolutionEvent history feeds signal modulation — saturation/dedup/ban_gene/plateau revived), `enable_gap_outcome_inference` (error-cleared ⇒ success bookkeeping, double-record guard), innovation-failure outcomes (ROI denominator), ATP spawn persisted to disk, `enable_windows_load_guard` (psutil CPU proxy where `os.getloadavg` is missing).
- **Quantitative fitness (22.2)**: `enable_fitness_cascade` — engine-owned validation cascade (ruff → mypy → pytest, short-circuit, per-stage timeouts); graded failure score (stage progress + pytest pass rate) flows into memory graph / innovation / events; untrusted `mutation.validation` (LLM-distilled) is never executed in this mode; failed EvolutionEvents land in `events.jsonl` (revives repair-loop breaker).
- **UCB1 selection (22.3)**: `enable_bandit_selection` — parent sampling `score × (1 + mean + c·√(ln N/nᵢ))`; `get_memory_advice` exposes per-gene `geneStats`; `--review` stays deterministic (module-level `_loop_review_mode`).
- **Niche archive (22.4)**: `enable_niche_topk` — per-signal top-3 preferred genes (solidify success anchors #1); permanent bans become 30-day probations (`probation_by_signal`).
- **Acceptance gray-scale (22.5)**: `EVOLVER_ACCEPTANCE_SHADOW` — gate verdicts recorded, never enforced; `acceptance/report.summarize_acceptance()` (interception / validation-disagreement / false-kill-risk).
- **Lineage lessons (22.6)**: `enable_lineage_lessons` — `parent_event_id` on events (fills the always-empty prompt slot) + "Lineage Lessons" block (selected gene's recent failures) in the GEP prompt.
- **Novelty gate (23.1)**: `enable_novelty_gate` — pre-cascade rejection sampling (ShinkaEvolve η=0.95) over added-line sets vs capsule diffs / event snapshots / rejected fingerprints; reversals do not false-positive.
- **Operator bandit (23.2)**: `enable_operator_bandit` — mutation category UCB1 sampling over graded outcomes; keyword category keeps the dominant prior; `force_category`/drift authoritative; personality safety downgrade still applies.
- **ATP spawn bridge (23.3)**: `enable_atp_spawn_bridge` — picked-up ATP tasks emitted as `sessions_spawn` when bridge mode is active.
- **Auto-commit (soak)**: cascade-mode success commits the accepted mutation (atomic evolution steps) so later failure rollbacks stop at the last acceptance.

### Fixed
- **Gap outcome attribution**: inferred outcomes landed under the current (post-fix, empty-signal) key — disconnected from the attempt niche, breaking geneStats/UCB1 data. Now attributed to `last_action`'s key.
- **Rollback cwd family (3 sites)**: cascade-failure / novelty / acceptance-gate rollbacks lacked `cwd` — would stash the ENGINE's repo instead of the workspace.
- **Rollback destroyed accepted work**: `stash --include-untracked` ate engine state (`events.jsonl`) and every prior accepted-but-uncommitted mutation in no-gitignore workspaces; rollbacks are now tracked-only + selective disposable-untracked disposal (engine dirs, `.pytest_cache`, `__pycache__` spared).
- **T0 acceptance gate blind to test deletion**: re-froze the current test set per run (deleted tests vanished from the denominator — "delete tests to go green" passed). Frozen IDs now load from the persisted baseline snapshot.
- **CI version assertion**: `__init__.py.__version__` was still 1.93.0 while CI asserted 1.94.0 (latent red) — now in sync at 1.95.0.
- **Novelty fingerprint pollution**: engine state dirs / `__pycache__` / committed engine-state diffs diluted or poisoned the fingerprint; fingerprint now pathspec-filtered and split into (full, added) views.

### Verified
- 3-cycle E2E + 12-cycle soak (scripted mutation mix): graded scores, novelty rejections, shadow interception (del_tests_break case: cascade green + T0 regressed), lineage chain, niche stats — all green.
- 3100 tests, ruff/mypy clean; flags default OFF keep 1.94.0 behavior.

## [1.94.0] — 2026-08-11

### Added
- **Sprint 20 — v1.94.0 parity**（锚定 Node evolver v1.94.0）：
  - **sandbox 安全加固**：`sandbox_executor` 禁 `--inspect*/--watch*/--conditions/-C` node flags（GHSA-jxh8-jh77-xh6g 后续）；`--version/-v/--help/-h` 豁免脚本文件要求（#607–609）。
  - **publish 验证闸**：loose-asset 发布默认沙箱可跑命令 `node --version`；沙箱必拒的命令发布时 400（`PublishValidationError`）；Capsule 同载 validation；`policy_check.is_validation_command_allowed` 与 sandbox 门共用实现零漂移。
  - **Claude 上下文基因家族** `gep/context_routing_gene.py`：6 基因内容寻址（prompt-budget ledger / schema routing / tool-schema lazy-load / skill-manual routing / transcript handoff / memory-index budget）；`asset_store` seed 升级追加机制（标记≥2 / 仅补缺 / filelock / 不覆写用户 store）；`genes.seed.json` 对齐 808 行语义。
  - **feedbackEnvelope** `gep/feedback_envelope.py`：label/indecision/conflict/attention-aware uncertainty/聚合契约（纯测试契约行为重写）。
  - **12 个上下文膨胀信号**：claude_code_context_bloat / context_explosion / tool_schema_bloat / skill_list_bloat / skill_manual_bloat / transcript_context_bloat / conversation_handoff_bloat / memory_index_budget / prompt_budget_measurement / lazy_load_schema / schema_routing_gene_request / token_budget_overflow（双语正则）。
  - **ssePlannedClose**：SSE duration ≤300s（Hub 上限）、planned-close 一次性闩锁、fetch 回退帧解析（event/data 分派）、计划关闭重置重连退避至 5s。
  - **solidify 过程助手** `gep/solidify_helpers.py`：blast 严重度阶梯 / 目录分组 / 漂移检测 / 失败原因合成 / 过程评分（含 hollow-commit 守卫）/ 基因类别选择 / forbidden-path 守卫。
- **a2a_protocol 契约套件**：6 → 55 用例（消息构建、fetch/publish 包络、execution_trace 合成、签名、unwrap、post_hub_envelope 错误路径、node_id 文件）。
- **工程闸门全绿**：ruff 885→0、`ruff format` 544/544、mypy strict 44→0；全量 **2900+ 用例通过**。
- **基线失败测试修复**：solo（Windows exit-1 平台分支）、lifecycle×2（store 旧前缀权威性 + EVOLVER_HOME 隔离）、webui×3（陈旧测试形状对齐分页契约）、router（node_id 缓存重置）。

### Changed
- Package version **1.89.14 → 1.93.0 → 1.94.0**（声明 Node evolver **v1.94.0** parity）。
- ruff 配置：移植模式规则（PLC0415/ARG00x/PLR09xx/PLW0603/SIM102/117/RUF001）全局豁免并附理由；tests/** 惯用法豁免。
- README Implementation Status 刷新至 Sprint 20。

### Notes
- a2a 深度剩余：心跳状态机 / 事件投递 daemon 级 E2E 仍可加深（演进方案.md Sprint 21）。
- v2.0.x（Node 独立发布线）评估列 Sprint 21.5。

## [1.93.0] — 2026-07-31

### Added
- **A14** `experiment/trigger_shift.py` — offline trigger/context overfitting evaluator + package exports.
- **A15** `scripts/harness_governance_check.py` — PR CI harness/evaluator governance gate.
- **A16** `cli_options.py` — proxy path flags `--home/--store/--settings/--env-file` on `evolver proxy`.
- **solidify learning helpers** — `classify_failure_mode`, `adapt_gene_from_learning`, `build_soft_failure_learning_signals`.
- **a2a `build_publish`** — single-asset publish + Capsule execution_trace guard.
- **schema/prompt enum consistency** — `render_enum*` + explore in GEP prompt schemas.
- **Static guards** — dotenv load order (#460), adapters `py_compile` (#542), Hub egress coverage (C7).
- **Direct solidify suite** — `tests/gep/test_solidify.py`.
- **git_ops pure-function suite** — path normalize/protected/constraint contracts.
- **WebUI observer depth** — get_asset_overview, list_candidates, list_asset_calls, get_lineage;
  list_runs/get_run multi-source aggregation; API routes /api/assets/overview, /api/candidates,
  /api/asset-calls, /api/runs?view=list, /api/runs/{id}.

### Changed
- Package version **1.89.14 → 1.93.0** (declared Node evolver **v1.93.0** parity baseline).
- CI: Ubuntu 3.12/3.13 required; **Windows advisory** job (`continue-on-error`) for platform regressions.
- README Implementation Status refreshed for Sprint 18–19 surfaces.

### Notes
- Depth gaps (a2a protocol surface, solidify contract breadth, observer polish) remain tracked in `演进方案.md`.

## [archived] Sprint 10: v1.89.14 → v1.90.0 catch-up

### Gap 1: Trajectory export — foundation + decryption + session sources (G10.1, partial)
- `gep/trajectory/` (new package): ports the core of `trajectoryExport.test.js`.
  - `builder.py` — `build_trajectories()` / `build_trajectory_from_rows()`:
    group proxy-trace rows by session into `evomap.coding_trajectory.v1`
    trajectories; per-turn extraction (provider, endpoint, response_id,
    previous_response_id, request/response bodies, reasoning, encrypted_content,
    per-turn tokens, error); tool-call extraction across Anthropic `/v1/messages`,
    OpenAI `/v1/responses`, `/v1/chat/completions` (declared tools vs actual
    invocations; Anthropic `tool_use` deduped by id); **full streamed
    tool-argument reconstruction** (Anthropic `input_json_delta`; OpenAI Chat
    delta + full-snapshot dedup; OpenAI Responses delta + `.done` override);
    Bedrock provider normalisation; language detection (keywords + file
    extensions); failure-correction marking; test-execution / code-edit /
    `test_commands` detection from tool inputs; stats (`turns`, tokens,
    `has_tool_calls`, `tool_call_count`, `tool_types`, `has_test_execution`,
    `has_code_edit`, `test_commands`).
  - `io.py` — `write_trajectories()`: atomic (temp + `os.replace`); a pre-placed
    symlink is **not followed** (PR #294 C4); owner-only `0o600` on POSIX.
  - `crypto.py` — `read_trace_rows_detailed()` / `decrypt_trace_row()`: AES-256-GCM
    under a node-secret-derived key with `secret_version` keyring selection;
    RSA-OAEP-SHA256 hub-key envelope unwrap with node-secret fallback;
    **fail-closed** (3 distinct messages) unless `--allow-partial`.
  - `sources.py` — non-proxy session logs: **Codex rollout** JSONL
    (`session_meta` + `response_item` records — message/reasoning/function_call/
    function_call_output/custom_tool_call/tool_search*), **Claude Code
    transcript** JSONL (`user`/`assistant` with `message.content` blocks), and
    **OpenAI generic-chat** messages JSONL (top-level role-tagged records,
    `prompt_tokens`/`completion_tokens`, `thinking`+`signature`, OpenAI
    `tool_calls`/`tool` outputs) — with reasoning turns, custom tool calls,
    tool-search events, and test-execution / code-edit / failure-correction
    detection; plus `detect_source()` classification.
  - CLI: `evolver trajectory --input <file|dir> --output [...]` auto-detects
    session logs vs proxy traces, recurses directories, and decrypts with
    `--node-secret`/`--hub-private-key`/`--node-secret-keyring`/`--allow-partial`.
- `tests/gep/trajectory/` (27 cases: 11 builder incl. full streaming + 10 crypto + 6 sources).
- **Deferred (niche vendor sources)**: Cursor vscdb (SQLite), Gemini
  CLI+Gateway, Kimi Wire — bespoke low-frequency parsers, each with its own
  format-specific test file.

### Gap 8: Force-update hardening (v1.90.0 contract)
- `force_update.py` (262→490+ lines): ports the portable subset of Node's
  `forceUpdate*.test.js` (Node-specific npx/degit/package.json/index.js/exit-78
  mechanics are N/A for Python and intentionally omitted).
  - **Sentinels** — `FORCE_UPDATE_BUSY` / `FORCE_UPDATE_NOOP` (distinct
    singletons; identity-comparable, no truthy collision).
  - **Concurrency guard** — module-level mutex in `execute_force_update()`: a
    re-entrant call mid-upgrade returns `FORCE_UPDATE_BUSY` without
    re-downloading; mutex resets via `finally` (and on throw). (Fills a gap: the
    docstring claimed a file-lock guard that was never implemented.)
  - **Idempotent floor** — `required_version` is a *minimum floor*, not an exact
    target: operator (`>=`/`>`/`=`) + leading-`v` normalisation; an install that
    already satisfies the floor returns `FORCE_UPDATE_NOOP` (no downgrade, no
    re-download). Anti-downgrade guard (#213): an unparsable current version is
    refused, not silently satisfied.
  - **Coded frozen failures** — every failure is an immutable result carrying a
    stable `code` + `detail`; `is_force_update_failure()` + `FORCE_UPDATE_FAIL_CODES`
    registry.
  - **Safe extraction** — `_safe_extract()` refuses Zip-Slip (path-traversal)
    entries (keep-list/tarball-fallback safety).
  - `report_force_update_outcome(noop/updated)` persists status (`skipped`/
    `success`); `noop` wins defensively.
- `tests/test_force_update.py` (+19 cases).

### Gap 9: Outbound sync resilience (v1.90.0 contract)
- `proxy/sync/outbound.py` (108→290+ lines): ports `proxyOutboundSync.test.js`.
  - **Body-size budgeting** — one size-bounded batch per flush
    (`EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES` env, overridable by store state after
    a 413); a single message that cannot fit is rejected, not sent.
  - **413 handling** — single-message 413 quarantines; multi-message 413 backs
    the budget down and leaves all messages pending (1 Hub call).
  - **Retryable vs terminal** — retryable per-message failures defer (status
    pending, retry count untouched, `next_retry_at` set); terminal finalises.
    `terminal` wins over retry hints (PR #301).
  - **proxy_trace gating** — `proxy_trace` dropped when
    `trace_collection_enabled` store state is `False`.
  - **Redaction** — Hub non-2xx response text redacted before persistence.
  - Rich result shape: `sent`/`synced`/`dropped`/`deferred`/`payload_too_large`/
    `error`/`responses`.
- `proxy/mailbox/store.py`: `Message.next_retry_at` field; `poll_outbound`
  skips deferred-not-due messages; new `defer()` (backoff without burning retry).
- `tests/test_proxy_outbound_sync.py` (new, 11 cases); `test_proxy_sync.py`
  updated to Node v1.90.0 `sent`=batch-size semantics.
- Encryption-envelope validation of `proxy_trace` payloads deferred to G10.1.

### Gap 5: Host Error Classifier (#571)
- `gep/host_error_classifier.py` (new): `is_host_client_error()` + non-global
  `HOST_PROVIDER_ERR_RE` — classifies 4xx provider errors (invalid_api_key /
  insufficient_quota / rate limit / MaxTokens / HTTP 4xx) with bare-number-safe
  context. `None`/non-str/empty → `False`.
- `gep/signals.py`: under a host client error the failure-streak path is
  skipped — no `ban_gene` / `failure_loop_detected` / `consecutive_failure_streak`
  / `force_innovation_after_repair_loop`; the actionable `host_llm_client_error`
  signal is surfaced instead. An LLM quota/auth storm can no longer ban a gene.
- `tests/gep/test_host_error_classifier.py` (new, 5 cases): ports
  `hostClientErrorSignals.test.js`.

### Gap 2: Solo mode (`--solo` / constrained-wild / "Mad Dog")
- `solo/` subsystem (new): `breaker.py` (network "no escape valve" hard cut) +
  `git_guard.py` (local-git-only guard, wired into `git_ops.run_cmd`) +
  `__init__.py` (banner). Solo state = `EVOLVER_SOLO` env (process-wide,
  import-race-safe).
- `cli.py`: `--solo` flag (implies `--loop`); activates before dispatch so env
  overrides + hub cut land at the source. Even a user-set `A2A_HUB_URL` is
  ignored. Validator daemon + ATP auto-spend + task pickup are hard-cut in both
  the startup path (`start_validator` returns `None`; ATP envs forced off) and
  the in-cycle path (`post_cycle` guards).
- `config.py`: `resolve_hub_url()` returns `""` under solo (no escape valve);
  new `MAX_CYCLES_PER_PROCESS` (`EVOLVER_MAX_CYCLES_PER_PROCESS`, 0=unlimited).
- `evolve/runner.py`: daemon loop honours `MAX_CYCLES_PER_PROCESS` (exits after
  N cycles — solo/CI testability).
- Fix: `cli._cmd_loop` now guards `add_signal_handler`/`remove_signal_handler`
  against `NotImplementedError` so `--loop`/`--solo` work on Windows
  (ProactorEventLoop lacks signal-handler support).
- `tests/solo/test_solo.py` (new, 11 cases): ports `soloMode.test.js`, including
  a subprocess smoke test asserting banner + service cut + clean exit.

### Stats
- **Tests**: +73 (5 host-error + 11 solo + 11 outbound + 19 force-update +
  27 trajectory); 0 regressions (1 pre-existing cognition test failure unrelated).
- **Baseline**: tracking v1.89.14 → **v1.90.0** (G10.5, G10.2, G10.8, G10.9
  closed; G10.1 trajectory core complete — proxy + full streaming + crypto +
  Codex/Claude/generic sources — Cursor/Gemini/Kimi vendor sources deferred;
  G10.3 cliContracts / G10.4 recipe pending).

## [archived] Sprint 9: v1.89.14 parity (7 gaps closed)

### Gap 1: Inert Gene Ban (#562)
- `gep/memory_graph.py`: `stable_no_error`/`heuristic_delta`/`predictive` outcomes
  now classified as **inert** — they build no Bayesian confidence and no longer
  count as successes for `preferredGeneId`.
- New `_count_trailing_inert()`: after `GENE_INERT_BAN_STREAK` (=8) consecutive
  trailing inert outcomes with no real success, the gene is added to
  `bannedGeneIds` so the selector yields null and the pipeline mutates.
- A single real success (e.g. `error_cleared`) resets the inert streak.
- 5 regression tests ported from `test/issue562InertGeneBan.test.js`.

### Gap 2: Node Secret Versioning
- `proxy/lifecycle/manager.py`: `parse_node_secret_version()`, `node_secret_version`
  property (store > env precedence), stale-secret detection (store version < env
  version → Hub rotated → clear store secret).
- `hello()`/`heartbeat()` persist the Hub-returned `node_secret_version`.

### Gap 3: Hub-Unreachable Exponential Backoff
- `proxy/lifecycle/manager.py`: `_record_hub_unreachable()` / `_record_hub_reachable()`
  / `_hub_unreachable_wait_ms()` / `hub_unreachable_backoff_ms()` — exponential
  backoff (5s→15min cap) on network errors (ConnectError/TimeoutException).
- `hello()`/`heartbeat()` check backoff before sending and record
  reachable/unreachable on success/failure.

### Gap 4: Anti-Abuse Telemetry Heartbeat
- `gep/anti_abuse_telemetry.py`: `build_heartbeat_anti_abuse()` — privacy-preserving
  envelope with HMAC-pseudonymized device/workspace hashes, source-confidence
  labels (hub_required/hub_service/hub_observed), integrity hashes, task timing.
- `config.py`: `ANTI_ABUSE_TELEMETRY_MODE` (default `heartbeat`, explicit opt-out).
- `proxy/lifecycle/manager.py`: heartbeat `meta.anti_abuse` injection when mode=heartbeat.

### Gap 5: Outcome Report Mode (P4-a Slice B)
- `config.py`: `OUTCOME_REPORT_MODE` (default `off`) + `outcome_report_mode()`
  resolver (on/enforce/true → `on`).

### Gap 6: Force-Update from Heartbeat
- `proxy/lifecycle/manager.py`: `_maybe_trigger_force_update_from_heartbeat()` with
  `EVOLVER_FORCE_UPDATE_RETRY_COOLDOWN_MS` (default 5min) — prevents Hub from
  hot-spinning force-updates on every heartbeat.

### Gap 7: Last-Update Ack
- `proxy/lifecycle/manager.py`: `read_pending_last_update()` / `set_pending_last_update()`;
  heartbeat carries `last_update_ack` + `node_secret_version` in payload.

### Stats
- **Tests**: 1573 → **1609** (+36 new tests, 0 regressions)
- **Baseline**: tracking v1.89.11 → **v1.89.14** parity on lifecycle + GEP selection

## [archived] Sprint 0-8 catch-up against evolver v1.89.11

### Sprint 0: Engineering baseline
- Fixed `gep/sanitize.py` `import json` position bug (was at file bottom, caused NameError).
- `gep/sanitize.py`: reverse leak scan now skips path/URL-shaped env values (#568).
- Added 6 credential redaction patterns (jwt, aws, github, slack, connection_string, high_entropy).
- `CHANGELOG.md` upgraded from stub to Keep-a-Changelog format.
- `CONTRIBUTING.md`: conventional commits with scope; baseline updated to 1331→1534 tests.

### Sprint 1: IDE runtime hooks
- Rewrote `adapters/scripts/runtime_paths.py` (24→315 lines): host-env project dir resolution,
  workspace-id atomic create with symlink guards, FS-only fallback.
- Rewrote `session_start.py` (41→211): workspace-scoped memory recall, non-git notice (throttled),
  dedup, lazy memory read from newest end.
- Rewrote `session_end.py` (48→214): HEAD~1 diff, workspace-id stamping, Cursor systemMessage suppression.
- Rewrote `signal_detect.py` (39→160): context-aware stratification, Claude Code payload parsing,
  multilingual (CJK) fallback.
- New `lock_paths.py` (52 lines): daemon singleton-lock location + lease staleness tunables.
- New `task_recall.py` (103 lines): `@evolver recall` triggered capsule recall.
- Updated `memory_filtering.py`: added `filter_relevant_outcomes` (Node contract).

### Sprint 3: Execution bridge + conversation sniffer
- New `gep/exec_bridge.py` (93 lines): Windows npm .cmd shim resolver (CVE-2024-27980).
- New `gep/conversation_sniffer.py` (240 lines): scan_corpus with local co-occurrence,
  off/shadow/enforce modes, cooldown, CJK support.
- Extended `gep/bridge.py`: added `determine_bridge_enabled()`.
- `evolve/runner.py`: Ralph-loop stale bridge-mode break (#559).

### Sprint 4: Security + seed library + deepening
- Expanded `genes.seed.json` (3→11 genes): full alignment with Node v1.87.0 seed library.
- Rewrote `gep/skill2gep.py` (187→400+): `parse_skill_md` with frontmatter + CJK sections,
  `infer_category` with word-boundary matching, `skill_to_gene_dict` with asset_id + quality heuristics.
- Deepened `gep/idle_scheduler.py` (220→300+): `EVOLVER_IDLE_OVERRIDE`, build-activity detection,
  FS-only idle fallback.
- `gep/schemas/gene.py`: added `avoid` and `_source` (alias) fields.

### Sprint 5: Multi-provider proxy routes
- New `proxy/router/gemini_route.py` (160 lines): Google Gemini API proxy with SSE.
- New `proxy/router/vertex_route.py` (145 lines): Vertex AI proxy with ADC auth.
- New `proxy/router/ollama_route.py` (140 lines): local Ollama proxy.
- New `proxy/router/responses_route.py` (150 lines): OpenAI-compatible API proxy.
- New `proxy/router/models_route.py` (85 lines): `/v1/models` aggregator.
- New `proxy/server/settings.py` (62 lines): proxy settings persistence.
- New `proxy/trace/extractor.py` (65 lines): multi-format token usage extraction.
- New `proxy/trace/usage.py` (60 lines): usage aggregator singleton.
- New `proxy/envelope.py` (45 lines): structured message envelope.
- New `proxy/inject.py` (50 lines): context injection + internal field stripping.
- Updated `model_router.py`: 5-provider upstream detection.

### Sprint 6: ATP CLI + mailbox transport
- Rewrote `atp/cli.py` (86→270): 15 subcommands (buy/orders/tasks/claim/deliver/settle/dispute/publish/policy/proofs/tier/order/status/enable/disable).
- Deepened `atp/atp_execute.py` (87→230): sandbox validation, structured proof building.
- Deepened `atp/atp_task_pickup.py` (99→200): ROI scoring, capability matching, concurrent limit.
- New `gep/mailbox_transport.py` (115 lines): proxy mailbox client with auto-start.

### Sprint 7: Missing modules
- New `gep/token_savings.py` (120 lines): token/USD cost savings tracker with monthly reports.
- New `gep/narrative_memory.py` (85 lines): evolution history narrative compressor.
- New `gep/memory_graph_adapter.py` (120 lines): advanced queries (success trajectory, failure clustering, fuzzy match).
- New `gep/directory_client.py` (75 lines): EvoMap directory service client.
- New `gep/oauth_login.py` (115 lines): OAuth 2.0 device-code flow with keychain integration.
- New `gep/claim_nudge.py` (75 lines): throttled task-claim suggestion generator.
- New `gep/device_id.py` (85 lines): cross-platform anonymous hardware fingerprint.
- New `gep/anti_abuse_telemetry.py` (120 lines): abuse pattern detector (flood/bypass/exhaustion).

### Sprint 8: Experiment framework + i18n + docs
- New `experiment/` module (4 files): agent_runner, metrics, comparison, cli — controlled A/B evaluation.
- New `README.ja-JP.md`: Japanese README.
- New `README.ko-KR.md`: Korean README.

### Stats
- **Tests**: 1331 → 1546+ (215+ new tests, 0 regressions)
- **Source files**: 192 → 217+ (25+ new modules)
- **Seed genes**: 3 → 11
- **Proxy routes**: 4 → 9
- **ATP subcommands**: 5 → 15
- **mypy strict**: 0 errors across all files
- **Baseline comparison**: v1.89.2 → tracking v1.89.11

## [1.89.2] - 2026-06-09

- Initial Python port release tracking Node.js v1.89.2.
- GEP data layer, evolution pipeline, Proxy infrastructure, ATP marketplace (partial),
  IDE adapters (partial), WebUI (partial).

[Unreleased]: https://github.com/EvoMap/evolver/compare/v1.93.0...HEAD
[1.93.0]: https://github.com/EvoMap/evolver/releases/tag/v1.93.0
