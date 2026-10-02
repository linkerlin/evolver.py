# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Added — 成本与配置采集先行（经验即证据 §5.7，round-106）

版本保持 **1.113.0**。

- **receipt schema 增 `cost`/`model`**（`bench/runner.py`，默认 `null` = unmeasured）：receipt 在求解**前**写入（记录求解看见了什么），token 用量与模型配置要**求解后**才可观测——两个字段显式留空，观测不到就说 `unmeasured`，不猜不零填。
- **`bench/cost.py`**：`record_cost` 求解后回填 receipt 的 `cost`（input/output/total tokens）与 `model`；`read_cost` 读回（`null` → `unmeasured`）。token 源为 relay 侧 `proxy/trace/extractor.extract_usage`（relay 看得见 LLM 流量）；model 以 relay 观测为准，`AGENT_MODEL` 只作线索（自报）。
- **纪律**：此步之前不出效率/迁移结论。采集先行，结论后到。
- **测试 5 根**：默认 unmeasured；回填 tokens+model；无 model 仍 measured；缺 receipt → unmeasured；回填保留 provenance 字段。

**测试**：新增 5 全绿；`tests/bench` 146 过（receipt schema 改动无回归）；ruff / format / mypy 绿。

### Added — 双向记录路线（影子）（经验即证据 §5.6，round-105）

版本保持 **1.113.0**。

- **`gep/record_route.py`**：两条定性方向（capability / adaptive）并行产出记录。`run_dual_record_route` 各出一份内容寻址记录；`build_direction_block` 让每条方向的上下文按 id 引对方记录（互见）；不打分、archive 全留。**是记录路线，不是种群择优**——`MULTI_PROPOSE_ROUTES` 保持 1，择优语义不解禁。
- **定位**：影子验证（SelfSearch 双 lineage 记录共享机制）。生产形态（LLM 驱动双 lineage 跑真实 episode）留后续；本步只验证共享机制端到端。
- **测试 4 根**：两方向各出记录；互见对方记录（判据）；方向枚举与 `other_direction`；archive 全留（两份记录都在）。

**测试**：新增 4 全绿；`tests/gep`（含 record_route / episode_record）27 过；ruff / format / mypy 绿。

### Added — improver 工具面进库（经验即证据 §5.4，round-104）

版本保持 **1.113.0**。

- **3 个 improver 工具基因入种子**（`genes.seed.json`，共 20 个基因）：`gene_improver_bounded_text_search`（有界文本搜索）、`gene_improver_line_range_view`（行区间查看）、`gene_improver_trajectory_reader`（轨迹读取）。均带 `target_hook=improver_tool` / `mechanism_family=improver_tools`，`asset_id` 经 `compute_asset_id` 实算（加载时内容寻址校验通过）。信号为检查侧（`long_output` / `search_output_truncated` / `trajectory_too_long` / `inspection_difficulty` 等），不与常见突变信号撞车。
- **记录自包含**（`episode_record.record_episode`）：存储前从基因库附着 `target_hook`/`mechanism_family` 到 episode 的 gene 字段——「使用率可从 episode record 复算」不依赖第二次查找。未知基因 id 优雅留空，meta-report 有库回退。
- **`meta_report` 新增 `improver_tools` 面板**：从 episode record 复算使用率（improver 工具轮数 / 总轮数，每轮计一次，对齐 SelfSearch Table 12 口径）。这是引擎对 improver 工具面的**选择率**，不是宿主自报的工具调用——与面板其余部分同一诚实口径。CLI `evolver meta-report` 打印该行。
- **测试 4 根**：种子含 3 个 improver 基因（asset_id 校验）；`record_round` 附着 target_hook；面板从 episode record 复算（含库回退）；无 episodes 时面板为空。
- **未决**：宿主装/卸的闭环依赖带走表第 1 项（Parent 库首写，等人写第一份）——基因已就位，装/卸执行待 Parent 库。

**测试**：新增 4 全绿；`tests/gep`（含 episode_record / meta_report / val_seal）+ `test_cli` + `test_swarm` + `test_mcp_server` 共 139 过；ruff / format / mypy 绿。全量 `-m "not slow"` 4088 过（唯一失败为下述已知 flake）。

### Added — 记录过 val-seal（经验即证据 §5.3，round-103）

版本保持 **1.113.0**。

- **`val_seal.SEAL_TARGETS` 增 `episode_record`**：密封面清单如实列出记录库。
- **存储前打码**（`episode_record.record_episode`）：正文递归过 `val_seal.redact`（`where="episode_record"`）——强 val 串替换为 `[sealed:val]` 后才计算内容寻址 id。泄漏串拿不到内容地址；弱串（短答案）永不裁决，只打码不判死。一轮的历史不因一个杂散 val 串而丢失，但秘密不进库。
- **测试 2 根**：构造泄漏样本（diff 含 val 期望）必被打码；`SEAL_TARGETS` 含 `episode_record`。

**测试**：新增 2 全绿；`tests/gep`（含 val_seal）+ `test_mcp_server` + `test_swarm` 共 133 过；ruff / format / mypy 绿。

### Added — 记录进提示词 + 线索层 + MCP 薄读（经验即证据 §5.2 + §5.1c 后半，round-102）

版本保持 **1.113.0**。

- **`gep/episode_clue.py`**（线索层）：宿主上报的 account / 工具动作是**线索**不是证据——append-only JSONL（`<EVOLUTION_DIR>/episodes/clues.jsonl`），逐条标 `source`，渲染时每条带来源标签。不入 episode record、不支撑门、不进验收维。
- **提示词三块序**（`gep/prompt.py` + `evolve/pipeline/dispatch.py`）：`## Previous Episode`（上一轮记录，引擎侧）→ `## Evidence Pack`（结果侧）→ `## Host Clues`（宿主上报，最弱垫后）。三块不混排、互不重复计数——记录侧证据先于结果侧分数。dispatch 只读 episode store 渲染上一轮摘要（`render_episode_block`，截断带标记）；写入口仍在周期边界。
- **钉收窄为写调用**：`record_episode(` / `append_clue(` / `episode_record.record_round(`——`record_round(` 裸扫会撞 `EvolutionSession.record_round`（会话账本，同名不同物），故只钉限定形式；读者（dispatch 读上一轮）不受影响。
- **`swarm_distill` 收回执**：宿主自由文本（去掉 fenced 资产块）作为线索入层，标 `source=host_distill`；dry_run 不存（没发生的轮的线索比没线索更糟）。
- **MCP `episode_get`**（§5.1c 后半）：薄读工具，走 `asset_*` 同一读法；工具面与回读各一钉。
- **测试 13 根**：`tests/gep/test_episode_clue.py`（5）+ `tests/gep/test_prompt.py`（2）+ `test_episode_record` 渲染（2）+ `test_mcp_server`（2）+ `test_swarm`（2）。

**测试**：新增 13 全绿；`tests/gep` 全量 + `test_mcp_server` + `test_swarm` 共 114 过；ruff / format / mypy 绿。

### Added — episode record 载体（经验即证据 §5.1a/1b + 1c 的 CLI 半，round-101）

本阶段第一件：把「一次自改进」立为一等对象（对照 arXiv:2609.37968v2，SelfSearch）。版本保持 **1.113.0**，阶段结束由人切。

- **`gep/episode_record.py`**：episode record 的引擎侧一半。一等对象 `e_k` 只收引擎自记（选中基因、diff、检查结果、门裁决）——宿主上报是**线索层**，白名单之外的键一律拒（`HOST_SIDE_KEYS` 单独报错，免得又把「宿主的细心程度」请回被评位置）。内容寻址 `sha256:` id（与 `library.py` 同一纪律）；**一轮只记一次**：同内容重记幂等 `already_stored`，同一轮异内容拒写（`EpisodeConflictError`）；`index.json` 是轮账，损坏即抛、不静默重开（重开就分叉历史）。`recorded_at` 取事件时间戳而非墙上时钟——重推导得同内容，否则幂等无从谈起。视图有界（diff 4000 / 检查至多 20 条 / 每条输出 400 / 全文 64k 上限，超限拒而非静默裁），完整现场仍在 `gep/evidence.py`——**不复制原始现场，不另起账本**：episodes = evidence 的有界可引用视图 ＋ 身份 id ＋ 索引。
- **写入口在周期边界**（调用图钉 `test_the_record_writer_is_absent_from_the_mutation_call_graph`）：`solidify.py` / `evolve/` / `bench/` 不得引用 `episode_record` / `record_episode`——变异路径写不进自己的记录。钉法照 round-93 的 `test_establish_is_absent_from_the_solidify_call_graph`。扫描名避开 `EvolutionSession.record_round`（同名不同物，会话账本；首跑即撞，钉收窄为模块名）。
- **接线**：`evolver solidify`（`cli._record_episode_round`）与 MCP `swarm_solidify` 收尾各记一轮，返回面带 `episode`；缺现场报 `scene_missing`——**报告而不猜**；记录失败不翻转好周期。
- **只读取用面**（§5.1c 的 CLI 半）：`evolver episode list|show <id>`。MCP 薄读工具下轮接。
- **测试 20 根**（`tests/gep/test_episode_record.py` 17 ＋ `tests/test_cli.py` 3）：内容寻址幂等、一轮一写、白名单拒宿主上报、越界拒写、索引轮账、坏索引不静默重开、按 event id 找现场、CLI list/show 回读、周期边界判据（一轮后按 id 读回完整记录）。

**测试**：新增 20 全绿；`tests/gep/test_library.py` 22 绿（相邻面）；`tests/test_cli.py` 16 绿；ruff / format / mypy 绿。

### Changed — 文档追平 round-97~99（round-100）

文档轮，按章程不算阶段进度。版本保持 **1.113.0**。

- **README（中英）状态表**：「multi-OS CI advisory / 多 OS CI 提示」自 round-94 起 已失实——Windows 是 blocking、round-98 起双平台跑锚套件，改为如实表述。CHANGELOG 导览行 round-96 → round-99。
- **AGENTS.md**：`instance_lock.py` 架构行更新为 OS 锁唯一真相语义（round-97）；坑阱篇补两条——同路径文件锁嵌套须 singleton 可重入（DEBUG #54）、进程互斥只有 OS 锁一个真相（DEBUG #52）。
- **CONTRIBUTING.md**：测试基线以实测更新（2026-09-30，**4078 passed**，13m01s），CI 描述补锚套件。
- ja/ko README 未动（其 CI 单元格只写「多 OS CI」，无失实表述）；史料不动；百分比快照保持原日期。

**测试**：全量 **4078 passed，0 failed**（13m01s；round-97 基线 4066 ＋ round-98 七钉 ＋ round-99 五钉）；文档一致性钉三根全绿。

### Changed — round-93 遗留的 CLI 钉补齐（round-99）

卫生轮，按章程不算阶段进度。版本保持 **1.113.0**。

- **`library establish-parent` 的 CLI 级四钉**（round-93 落地时只有手工烟测，属本仓自己的未完成项）：成功路径写 `parent.json` 且 `active` 保持空（输出含 untouched）；缺文件 exit 2；非 dict JSON exit 2；`--json` 输出可解析且带 sha256 快照 id。
- **`bench prompt --library` 的 CLI 透传一钉**：命令行指定的快照 id 与正文都出现在 prompt、active 不动。
- **观察到一次 flake**：`test_cli_webui_token_generate_and_revoke` 单次 SystemExit（三跑两绿，顺序敏感，无复现路径）。未回填 DEBUG——再出现即立簿追根因。

**测试**：CLI 22 过（test_cli 13＋bench_cli 9）；ruff / format 绿；无 src 改动，mypy 与全量基线维持。

### Changed — CI 跑锚套件 + `__all__` 完整性钉（round-98）

卫生轮，按章程不算阶段进度。版本保持 **1.113.0**。

- **锚套件进 CI（双平台）**。ubuntu 与 Windows 两个 job 各加 `anchor init` + `anchor run`——DEBUG #46（锚探针模板漂移，契约变更未同步冻结面）这类缺陷从此由 CI 拦截，不再等下一次 epoch 重播种才发现。CI 上的播种是临时 runner home 的构建检查，不是人的仪器首写。两步命令已按 CI 渲染原样在本地一次性环境复演（epoch 1、17/17 PASS）。
- **`tests/test_all_exports.py`（外部审阅 M5 的最简解）**：七个手工维护 `__all__` 的模块（config / library / hypothesis / cursor / bench 三件）逐一钉「每个导出名在模块上存在」——typo 即红，不再等到第一次 `import *`。落地即抓到一条事实：`asset_store` 根本没有 `__all__`（400 行模块全公开导出）——钉的职责是校验既有清单而非强制新清单，该模块记注后移出名单。
- 跨会话记忆同步至 round-98。

**测试**：新钉 7 过；快速面 4049 passed ＋ 24 deselected（总量 4073＝round-97 全量 4066 ＋ 新钉）；ruff / format 全绿（本轮无 src 改动，mypy 维持）。

### Changed — 外部审阅三真缺陷落地修复：锁窃、盲 cast、无锁追加（round-97）

外部审阅（Antigravity 报告，round-96 前一轮已逐条核实）中三条成立项作为一轮卫生修复落地。按章程不算阶段进度。版本保持 **1.113.0**。驳回项维持：C2（TypedDict 管线上下文）顶撞 AGENTS 规范篇成文规范；C1（拆 cli.py）章程明说不立项，记录在案。

- **#52 单实例锁重写（OS 锁为唯一真相）**。旧 mtime 启发式三宗罪：活守护跑满 5 分钟即「过期」可被后来者偷锁；双启动同判 stale 互删成双实例（TOCTOU）；`release` 无条件 unlink，未持锁进程一次误调删掉别人的活锁。现在直接 `FileLock.acquire`——活持有者任何年龄不可窃，崩溃残留（无 OS 锁）自然复用，拿到锁写 PID（诊断用），release 只删自己持有的。钉六根，含子进程活持有者把 mtime 拨到 4000 秒前仍不可窃。
- **#53 非 dict JSON 运行时拒**。`_safe_json_loads` / `read_json_if_exists` 的 `cast` 对合法 JSON 的 list/str/int 原样放行，调用方 `.get()` 即崩；现在 `isinstance` 校验，非 dict 与哈希失配同族按损坏跳过。
- **#54 JSONL 追加串行化（修复中自撞出第四缺陷）**。`append_jsonl` 上 sidecar 锁（daemon 与 MCP 服务器两活进程写同一文件，Windows 无 O_APPEND 保证）；上锁后 5 个既有测试 30 秒超时——`append_event_jsonl` 等三个包装层早已同路径持锁，同进程两 FileLock 实例在 Windows 不可重入。`with_file_lock` 改 `is_singleton=True`（进程内按路径单例＋引用计数，嵌套即重入），套件 152s → 1.5s。这一条同时消掉了一个先于本轮存在的嵌套死锁隐患。

**测试**：`test_instance_lock.py` 重写为六钉（新语义）；`test_asset_store.py` 增五钉（非 dict 三、锁契约与并发线程 100 行完整）。全量回归 **4066 passed，0 failed**（10m44s，round-95 基线 4059 ＋ 净增 7 钉）；ruff / format / mypy strict 全绿。DEBUG.md 回填 #52–#54。

### Changed — 文档全面同步到 v1.113.0 / 库即尺子（round-96）

按章程此轮不算阶段进度（文档轮）。版本保持 **1.113.0**。边界：两份史料（RSI演进对照、wikiskill 对照版）不动；产品说法不重写（round-90 裁决）；百分比快照保持其 2026-09-05 日期（改日期即伪造）。

- **DEBUG.md 回填 #47–#51**（章程要求修完回填，本会话五条真修复入簿）：假说折账读已焚文件（round-91，16 条空串的根因）；Windows PATHEXT 探测盲区致级联静默跳过（round-88，与 #2 同症状异根因——复发对号经验）；平台断言三族（pathsep 切分 / cwd-rmtree / resource win32 mypy）；redact 空文本缺键（round-95，早退路径是 API 契约盲区）；CI 多行 `python -c` 即语法错（round-94，渲染后演练经验）。
- **AGENTS.md 架构篇**：`bench/` 包整体入树（八模块：tasks/builtin_pack/scoring/prompts/runner/frozen_gate/compare/regression_guard——此前完全缺席）；gep 补五个新模块（evolution_session / hypothesis / val_seal / cursor / library）。**坑阱篇**补四条：Windows 工具查找走 `shutil.which`、PATH 继承断言用子串、跑全量时勿改源、CI 改动按渲染后命令演练。
- **SKILL.md CLI 速查表**：补齐缺失的整个测量与治理命令族（session / bench / anchor / library / gate-report / meta-report / hitl / supervise / gene-lifecycle / soak / mcp / skills / workflow）——此前表格止于 ATP 命令。
- **README 四语同步**：主 README 的 CHANGELOG 导览行（残留 1.112.0）更新至 round-96；日文 / 韩文 README 的总评行与版本格同步到 1.113.0——收束事实（八会话无胜者）与现阶段（库即尺子）如实写入，产品定位措辞不动。
- **CONTRIBUTING.md**：测试基线从 2026-06-15 的 1331 更新到 2026-09-27 的 4059 ＋ mypy strict 0 错；补一句 CI Windows 已是 blocking。

**测试**：`test_docs_consistency.py` 三钉全绿（版本一致性钉覆盖本次所有改动文件）；无代码改动，无需全量重跑（round-95 基线 4059 维持）。

### Changed — 测试针一轮：四个裸模块补 1:1 测试，一处真不一致修复（round-95）

按章程此轮不算阶段进度。版本保持 **1.113.0**。差距盘点方法：名字映射（146 个无 1:1 文件，高估——探针经 `test_anchor` 覆盖、pipeline 经集成覆盖）校准为真实覆盖率（`--cov` 分支模式，快速面）：**总量 79%、70 个文件全覆盖**；阶段核心（solidify、frozen_gate、bench.runner、hypothesis、cursor、library、evolution_session、regression_guard）全在全覆盖名单里。缺口集中在章程冻结的 proxy/webui/atp 面，不补。

- **`tests/bench/test_scoring.py`（22 钉）**：四种评分器的边路——缺交付物、坏 JSON、越界路径、崩溃脚本、超时、未知类型、不可解码字节、分数恒在 [0,1]；`_normalize` 语义钉死（行尾空白与首尾空行归一，**行首空白与内部空行是内容**——测试初版写错语义，纠正时顺带把这条语义显式钉住）。
- **`tests/bench/test_tasks.py`（20 钉）**：`validate_tasks` 全错误族（非列表/非对象/坏 slug/重复 id/坏 split/空 prompt/空 sandbox/路径穿越/评分器字段缺失）＋ `materialize` 的幻影评分防御（force 删未声明陈旧文件与目录、force=False 保留、幂等）。
- **`tests/bench/test_prompts.py`（12 钉）**：绝对 workdir、禁离场、标题题面、读回提醒、exact/code_stdout 措辞分叉、library_block 位置（Task 与 Deliverable 之间）与空块视同缺席。
- **`tests/gep/test_val_seal.py`（20 钉）**：未武装全惰性；train 共享材料是公共非秘密（落盘验证）；短答案弱信号永不裁决（「chapter 2」不触发）；强命中 `assert_sealed` 抛错；redact 替换并计数、弱串不动、非字符串期望 JSON 化；秘密去重且按长度降序。
- **一处真不一致（钉子落地即抓到）**：`val_seal.redact("")` 的早退路径不带 `redacted` 键，调用方无法统一读数——docstring 说「计数被报告」。已修：空文本路径也带 `redacted: 0`。
- **staleness 假阳性定性**：覆盖率跑中 `test_status_reports_staleness_surface` 失败，根因是套件运行期间源文件被本轮编辑（mtime 新于进程启动，`stale` 如实报 True）——测试正确，流程竞态自造；单独跑、同过滤跑均过。教训入账：跑全量的同时不要改源。

**测试**：新增 74 钉全绿；ruff / format / mypy strict 全绿；全量回归 **4059 passed，0 failed**（12m16s，round-94 基线 3985 ＋ 74 钉）。

### Changed — 系统审阅落地：CI 升格、文档钉、求解回执（round-94）

全仓审阅（测量自证、指挥文件漂移、平台债三处系统性风险）的处置落地。仪器加固一轮，按章程不算阶段进度。版本保持 **1.113.0**。

- **CI：Windows 升 blocking**。`test-windows` 原是 `continue-on-error` 咨询位——round-88 的 8 个失败（PATHEXT 级联回退、`os.pathsep` 断言、Windows cwd 删除竞态、win32 mypy 假阳性）全靠开发机恰好是 Windows 才撞见。修复后套件在本机全量绿，失败即真缺陷，去掉豁免。顺带拆掉一颗哑弹：CI 里硬编码的「Assert package version is 1.95.0」自 1.95.0 起必红，改为 pyproject ↔ `__version__` 自洽断言（首版多行 `python -c` 缩进会 IndentationError，本地按 CI 渲染复验后改单行——CI 改动必须本地按渲染后命令演练，这条算学费）。审阅勘误：Windows job 一直存在，缺的是牙，不是有无。
- **指挥文件一致性钉**（`tests/test_docs_consistency.py`，纯文本零引擎导入）。本阶段三起漂移（round-88 重派已落接线、round-93 禁令按字面到期＋SKILL 携带已废设计、round-94 README 版本残字）。三根钉：粗体版本声明须与 pyproject 一致（动态读，不写死，人切版本时文档随更）；指令文件（README×2/AGENTS/SKILL/TODO）不出现已废措辞（「受治理的仓库自维护」「家规」「conventions, not derivations」——章程 §4 豁免，记史是其职责）；阶段标记在四个阶段文件必须在场。钉子落地即抓到真漂移一条：`README.md` 状态表仍写 `version **1.112.0**`，已修。TODO 第 3 行的已废措辞引用收干为「见章程 §4」——工作清单不存档，废因住章程。
- **求解回执（只捕获，不执法）**。测量自证缺口：八会话战役里门每轮重评同一份旧解而账本只记 flat，机器无法知道没人重解。`bench prompt` 现在在沙箱旁 `_receipts/<task_id>.json` 写 `evolver.solve_receipt.v0`（pack digest、注入的快照 id 或 null、replicate、时间戳）——放在沙箱外，解题的宿主伪造不到。执法（回执与基线/门的绑定、快照新鲜度）**留到点名裁决**：绑定语义依赖「解的是哪份库」的定义，现在硬上要么打断测试生态、要么 fail-open 糊弄，都不诚实。
- **点名检查单**（入 TODO）：① 候选快照在 run record 的槽位；② 回执绑定与新鲜度；③ 求解上下文隔离层级。
- **记录在案不动**：`verify_charter_pack.py` 的归宿两选一（入仓 / 升锚探针 epoch 14），由人定；`cli.py` 3065 行、夹具重复（`git_ws` ×9）、proxy/webui/atp 完整度参差——章程冻结中，不顺路不值得动；三处版本字面测试钉是刻意绊线（版本只由人切），保留；sandbox_executor Windows 无资源上限仅超时，本地威胁模型内可接受。

**测试**：`test_docs_consistency.py` 三钉、`test_bench_pack.py` 增三钉（回执字段、注入 id 入回执、失败不写回执）；全量回归 **3985 passed，0 failed**（10m12s，round-93 基线 3979 ＋ 六根新钉）；ruff / format / mypy strict 全绿。

### Changed — 库即尺子机器就位：establish 首写入口 + 按快照 id 的求解注入（round-93）

裁决放行的引擎侧第 2、4 步：只落机器，调用与内容不动。出题与写 Parent 库仍冻着；当前锚侧 bar 1.0 的包上不开新会话；本函数本轮不被调用，soak 的 active 保持空（已核验：soak 无 library 目录）。版本保持 **1.113.0**。

- **第 2 步：`library.establish_parent_library()`**（`establish_*` 族，`establish_parent_baseline` 同一纪律）。存快照（`save_version`，内容寻址、同内容幂等、异内容冲突拒写）＋写 `parent.json` 指针。`active` 按构造不动——`_set_active` 的唯一调用者仍是 `publish()`（Accept-only），首写与 Accept 不合用一条路。重立不同内容是人的 CLI 决定，回执带 `previous`，旧快照永不删除。**调用图钉**：`test_establish_is_absent_from_the_solidify_call_graph` 扫 `solidify.py` 与 `evolve/` 全部源码，出现该名字即失败。CLI：`evolver library establish-parent --from=<file>`。
- **第 4 步：求解按快照 id 注入**。`bench prompt` 增 `--library <snapshot_id>`：`load_version(id)` 只读取，`render_prompt_block` 把快照正文**贴进 prompt**（4000 字符预算），并保留沙箱限定——宿主不被告知去开任何库目录。Parent 求解注 Parent id、候选求解注候选 id（候选 id 将来来自只存储不改 active 的 `save_version()`，不来自 `publish()`）。id 不存在是报错，不是静默出一份没有库的 prompt；不带 `--library` 的 prompt 逐字不变。
- **两处失效句子修正**：TODO 的禁令改为「在一份满足第 3 行的题被点名之前，不写 Parent 库、不出新题；点名本身另算一次裁决」（原句在上次提交里已按字面到期）；SKILL.md Current stage 换成 round-92 的 train 可收回设计（原句还在派发已废的家规）；README.zh.md 总评切 1.113.0。
- **AGENTS 命令篇**：补 `library establish-parent` 与 `bench prompt --library` 两行。

**测试**：`test_library.py` 增七钉（首写前无 Parent、建立不动 active、同内容幂等、异内容换指针报 previous、`save_version` 单独不移动任何指针、调用图缺席、render 粘贴正文＋保留限定＋超预算截断）；`test_bench_pack.py` 增三钉（无 `--library` 的 prompt 无库段、指定 id 贴正文且保留限定且 active 不动、未知 id 报错）。受影响面 111 过；全量回归 **3979 passed，0 failed**（8m56s，round-88 基线 3967 ＋ 新钉）；ruff / format / mypy strict（339 文件）全绿。

### Changed — 库即尺子第 3 步设计修正：条款来自 train，不许抄写 Accept（round-92，裁决）

round-91 落进章程的第 3 步（「家规只在写库人脑子里」）经裁决废止，未开工即改。版本保持 **1.113.0**（已按「协议落地、没有适应度胜利」切过，不再切）。

- **为什么废**：那套设计测的是抄写，不是进化。家规不在题面里、也不在 train 的前后观察里，正确句子只存在于评分器和写库的人脑子里——空库把 Parent 钉在 0，第一份把句子写进快照的候选再被求解抄进答卷，就白得一次 Accept。这和上一阶段把 bar 顶在 1.0 是同一类导演，只是方向朝下；round-85 不许候选给自己写及格线，这条路是出题人给候选写及格线。
- **第 3 步改写（`演进方案.md` §5）**：决定性条款必须能从 train 的前后观察里唯一收回来，val 题面里不出现。Parent 求解只看 Parent 快照和 val 题面；候选求解只看候选快照和同一批 val 题面；写候选的宿主看 train，不看 val，也不看 grader。空库 Parent 拿不到那条从 train 里蒸馏出来的约定。若这样测出的 Parent 仍满分——宿主不读库也能猜中——这次测量结束，不改题面再测。
- **第 2 步入口分家**：形状对（不带变异的首写、solidify 碰不到），入口不对。移动 active 的只有 `publish()`、文档写明 Accept-only；首写是另一个函数（`establish_*` 族）带自己的命令行入口，**不给 `publish()` 加入口**——否则首写和 Accept 合用一条路。函数就位之前不写 Parent 库。
- **第 4 步按快照 id 读**：不复用 enrich 的 `_consult_library()`（读 active；对比期间 active 指 Parent，候选草稿条款不在那里）。求解入口按 id 注入——Parent 求解放 Parent 快照 id，候选求解放候选快照 id，都走 `load_version()`，都不移动 active。
- **完成判据收窄（`演进方案.md` §4）**：「库里有句子、答卷里有句子」的 Accept 只证明求解路径读了快照，不算。本阶段的 Accept：候选快照里的条款只来自 train 观察，val 求解只靠这份快照，两遍都严格高于只持有 Parent 快照的 Parent。
- **禁令**：第 3 步按新句落地之前，不写 Parent 库，不出新题。历史那 16 条空 `hypothesis` 不回填——d0cd927 已修焚毁顺序并钉死拒绝轮必须带正文，旧账保持原样。
- **对账确认**：八场 incomplete / `unreliable_evaluation`、各 2 轮、16 Reject、0 Accept；产品树改动只有 c2b1b10 的 15 个 mypy 修复；作废「收窄说法、关臂」维持；Evolver.php 与 EvoScientists 不进这个门。

## [1.113.0] — 2026-09-27

配对会话门已落地；没有候选在密封 val 上优于 Parent。这是本版的发行说明全部——不写适应度胜利。同轮开启下一阶段「库即尺子」。

### Changed — 阶段收束 + 假说账本卫生账 + 库即尺子开阶段（round-91）

- **配对会话阶段收束**。八次会话（run_1..run_8）全部 `incomplete`（`unreliable_evaluation` 判停，各 2 轮），`rounds.jsonl` 16 Reject、0 Accept。它证明的是治理机器能拒绝发布，不是仓库被进化改好了：0/1 满分标尺分辨不了候选，门停在 flat 是对的。原 §4 第 2 条的两条结局措辞（说法收窄、关臂）经裁决作废——无臂可关（种群、bandit、niche、ATP bridge 开赛前就是关的），产品说法不动（README/AGENTS 从未改过）。
- **版本切 1.113.0**（pyproject / `__init__` / 三处 MCP 状态测试钉）。README 总评行改为：配对会话门已落地，没有候选在密封 val 上优于 Parent；库即尺子阶段开启。
- **账上的两个洞（下一阶段的开工理由）**。其一，八场 `run.json` 的 `parent_snapshot` 全是 null——没有已发布库，会话冻进的是空，「active 不动做 Parent/Candidate 的 val 评分」（章程 §5 第 4 步）一次都没发生；跑过的是仓库 diff，裁判是宿主微任务，这些题宿主已经会做，基因与代码 diff 都推不动分数（v2 包预注册失手点被逐字做对、两遍 230，说明的是同一件事：规则写在题里，库帮不上忙）。其二，16 条 `rounds.jsonl` 的 `hypothesis` 全是空串——`solidify()` 先跑 `_solidify_cycle()`，周期末尾 `clear_hypothesis()` 焚毁假说，返回后才 `_pending_cycle_context()` 去读；函数自己的说明写的是焚毁前读。八场在程序上合法，在假说层无法复盘。
- **卫生账（已修，不算阶段进度）**：`solidify()` 现在在调用 `_solidify_cycle()` **之前**取出假说正文，交给 `begin_round` 写进账本。钉：`test_the_ledger_remembers_the_burned_hypothesis_text`——拒绝路径的 `rounds.jsonl` 必须携带声明过的假说正文。
- **下一阶段章程（「库即尺子」，已写入 `演进方案.md` §4/§5）**：只做一件事——让被进化的对象本身成为评分对象。顺序：① 补账本（本轮已完成）；② 人写第一份 Parent 库，与 `evolver bench baseline` 同型的不带变异首写，solidify 碰不到；③ 密封题的决定性条款只放库里不放题面，条款用约定不用推导（「平局取较早 id」类家规），Parent 只查 Parent 快照、候选只查候选快照、同一宿主同一批题——空库 Parent 写不出家规，bar 低于满分，候选写进库且求解真的读到才可能严格优于；④ 求解入口把查阅到的快照放进 prompt（现在 `bench prompt` 只有题面和沙箱，库不在场，内容维发布了也不改变分数）。
- **边界**：不开第三份「把宿主难住」的包；不开 LLM Judge；不移植本体五类记录；K=2、bandit、niche 维持关闭；PHP 端口（Evolver.php，停在 2026-04 / v1.69）不追这次协议，EvoScientists 是研究代理的文档分叉，与本门不是同一个实验。
- **旁边两条线不拉进来补课**：Evolver.php 与 EvoScientists 见上条。

**测试**：`test_paired_session_solidify.py` 15 过（含新钉）；ruff / mypy strict（339 文件）全绿；版本钉随切。

### Changed — 八会话收束，章程第 4 节第 2 条达成（round-90，收口）

TODO #6 的完成条件按第 2 条达成。版本保持 **1.112.0**（阶段结束由人切 minor）。`EVOLVER_ACCEPTANCE_SHADOW` 保持打开，T0 soak 门仍只记录。

- **八次配对会话全部合法收束**。run_1..run_8，每场 2 轮真周期（`session hypothesize` 预注册假说 → `evolver run` 五阶段流水线 → `evolver solidify` 全级联），随后判断性停止（`unreliable_evaluation`——0/1 评分在 1.0 的 bar 上无法分辨任何候选）。soak 根 `evolution/sessions/` 的 `rounds.jsonl` 逐条在案：**16 轮、16 次 `decision: reject`、0 次 Accept**；每场结束均 no publish、cursor 未动。
- **会话 1 第 1 轮的拒绝是真缺陷**：级联的 mypy strict 抓到 15 个类型错误（round-82..87 新模块占 9 个）——协议第一轮就抓到真问题，已修复并单独提交（c2b1b10，mypy 339 文件 0 issues）。其后 15 轮全级联（ruff + mypy strict + pytest not slow）通过，包门一律 `flat`（两遍 [1.0, 1.0] vs bar 1.0，五题 per-task 地板全守住），与预注册的饱和标尺判定一致。
- **收口判据（章程第 4 节第 2 条）**：协议生效后八次会话结束（每场在至少两次 Reject 后合法 Incomplete），仍无一次「候选在密封 val 上严格优于 Parent」的 Accept。
- **步子哥裁决（同轮补记）：说法不改，关臂为空操作。**「受治理的仓库自维护」与「关掉从未赢过的臂」是章程 §4（演进方案.md:60）预注册的两条结局措辞，回执原样引用；裁决后均不执行——README/AGENTS 保持原样（本就未动过），该条款作废；种群（K=2）、bandit、niche、ATP bridge 开赛前就是关闭状态（本阶段边界，见 AGENTS.md 演进篇），无臂可关，维持即可，无代码与文档动作。minor 切不切由人定。引擎行为无任何变化；shadow 与全部安全门维持原状。全量回归基线：3967 通过（round-88）＋ mypy strict 全绿（c2b1b10）。

### Changed — 收口路线点名：换包（round-89，裁决）

TODO #6 点名为换包。版本保持 1.112.0。`EVOLVER_ACCEPTANCE_SHADOW` 保持打开。本轮无代码改动。

- **八会话留到新 Parent 仍满分时再用。** 第 4 节第 2 条记的是搜索跑完仍无 Accept。现行 0/1 小包上 Parent 已是 1.0，Accept 没有分数空间；现在开会话，收窄说法时记下来的是满格尺子，不是进化结果。
- **换包是替换锚侧文件的字节。** `freeze_charter_pack` 只调用 `write_pack()`，产物与 digest `721a33d8de3a0b6e` 相同。digest 不变，基线继续有效。`evolver bench freeze --force` 会把锚侧手装的包盖回这份内置 12 题。
- **新包要给严格优于留出格。** 评分是 0 与 1。val ≤ 6 时 Parent 至少一题为 0；val > 6 时 Parent 至少 8 题为 0，否则 `COMPARE_MIN_DISCORDANT` 到不了。题由人写，不走自博弈出题。先放包，由不写候选的测量解完 val，再 `evolver bench baseline`。新 Parent 仍满分就转入八会话，不准备第三份包。
- **`evolver session start` 排在新基线低于满分之后。**

**下一步**：锚侧新包，一次 `evolver bench baseline`。第 6 项仍要真实会话数据；换尺子不算阶段进度。

**执行回执（同轮补记）**。`charter-pack-v2.tasks.json` 按字节拷贝至锚侧（`cmp` 逐字节一致，digest `dfd9f8cada3740b4` 保持），验尺脚本 FIT。5 道 val 由本上下文仅凭 `bench prompt` 题面与沙箱输入求解 × 2 遍，未读 JSON 里的 grader：`val-code-div3` 的 sum.py 自测输出 120，与作者参考解一致；`val-ledger-posted` 按规则逐字落地，手推与独立解释器对拍均为 230，r2 对 r2 字节重放同为 230。`bench baseline` 一次：**Parent = 1.0**，两遍五题全 1.0，per_task 地板全 1.0，绑 `dfd9f8cada3740b4` + epoch 13，落 soak 根。

**预注册失手点未兑现**。RULES.txt 没有藏规则：`void H` 因双命名空间落 post 侧被忽略（「void 一个 hold id 会关掉它」那条捷径不成立）、capture 把 posted 打到 −15（「posted 不允许为负」是捷径）、void 负额 post 反向加账 15、capture Z 60 只取 50（「不足额改成部分冻结」是捷径）、输出 posted 本身 230 而非 available 205。解题上下文知道包里有一道要失手的题，仍尽了全力——规则可解则解，不是沙袋测量。

**决策树触发：新 Parent 仍满分 → 按 round-89 转入八会话分支，不再写第三份包。** 下一动作是 `evolver session start`，由人点名；八次会话（预算耗尽，或至少两次 Reject 后合法 Incomplete）无 Accept，即按章程第 4 节把说法收窄为「受治理的仓库自维护」并关闭从未赢过的臂。换尺子不算第 6 项进度。

### Changed — 仪器武装 + 全量回归首次全绿（round-88，round-86/87 遗留清账）

收口序列真机执行完毕，配对会话的测量仪器从此在线。版本保持 1.112.0。

- **锚纪元 13（须步子哥执行的那一步）**。`anchor init --epoch 13` 装入 17 cases，`anchor run` 全 PASS。epoch-12 的 `bench-pack-gate` 探针仍断言首次武装原因是 `baseline_established`，与新契约（`no_baseline` 且不写基线）失配——重播种即为换约，这是 epoch 机制的设计用途。
- **Parent 基线写入：1.0**。`bench freeze` 冻结 12 题内置包（7 train / 5 val，digest `721a33d8de3a0b6e`），5 道 val 沙箱由本上下文求解 × 2 遍（本上下文不写候选，§5.2 的独立测量约束由构造满足），`bench baseline` 两遍均 1.0。基线 v1 记录带 per_task 地板与 `anchor_epoch: 13` 绑定，落在仓外 soak 根（`$EVOLVER_HOME/evolver.py-soak/gep/acceptance/`），运行态不进产品 git。
- **重要事实：bar 在天花板**。Parent 1.0 意味着此包下任何候选 ≤ 1.0，第 4 节的「严格优于」不可能打穿。往后两条路由人点名：换更难的包（`bench freeze --force`，作废基线重测 Parent），或走「八次会话无 Accept」分支收窄说法。这是诚实测量的结果，不是仪器的缺陷。
- **全量回归首次有数字**：3967 passed，0 failed（8m42s）。round-87 之前的「全量回归见下」一直欠着，这次补上——代价是暴露了 8 处失败，全部当轮修掉。
- **一处真引擎缺陷（Windows）**：`get_fitness_cascade_commands` 的 venv-bin 回退用裸 `bin_dir / "ruff"` 的 `is_file()` 探测，而 Windows 工具是 `ruff.exe`——裸 venv + 洗净 PATH 的真实 dogfood 场景下整个级联被静默跳过。现在先试精确文件名（POSIX 布局），再退 `shutil.which(path=bin_dir)`（尊重 PATHEXT）。
- **conftest 跟上 round-86**：`armed_pack` 的 `rearm()` 重写基线时补 per_task 地板（v0 形状现在被回归守卫以 `baseline_without_per_task` 拒绝——守卫按设计工作，fixture 是旧契约的遗留）；新增 `rebind()`，测试体内重播种锚之后把现有 bar 重绑新纪元（否则 `protocol_drift` 拒绝）。
- **三枚冻结探针更新（epoch-13 契约的一部分）**：`dup-solidify-refused` 在首个 solidify 前声明假说并武装最小包门（无包即拒之后，探针必须自带仪器）；`rollback-cwd-alignment` 清理前把进程 cwd 移出沙箱（Windows 不能删除任何进程的 cwd，WinError 32）；`validation-env-and-tail` 的继承断言改子串判存活（Windows pathsep 是 `;`，POSIX 风格继承值整串成单元素）。
- **测试的平台适配**：`test_validation_env_prepends_tool_dirs` / `test_path_prepend_survives_sentinel` 同样改子串断言，homebrew 断言按平台收窄（该目录仅 macOS 存在，`validation_env` 只前置实际存在的目录）；`test_e2e_sprint14` 的 CLI 全链路测试补 §5.3 假说声明 + §5.2 包门武装（假说引用包内 train 题 id）。
- **文档对齐**：`AGENTS.md` 演进篇、`SKILL.md` Current stage、`演进方案.md` §2 三行与 §5 步骤 1–3 不再派发已接完的接线；章程如实记录假说 id 双 scope（周期 id ∪ 会话轮 id，`require_for_gate` 的 `also_accept`）为既定设计，比原稿「只能是周期 id」宽。

**测试**：全量 3967 通过。8 处修复的钉：`test_acceptance_shadow_lineage`（rearm 地板）、`test_anchor` 种子套件（三探针）、`test_anchor` 锚钩子（rebind）、`test_solidify` / `test_validation_env`（平台适配）、`test_solidify_dogfood_fixes`（引擎 which 回退 + 假件签名）、`test_sprint26_promotion`（rearm 地板）、`test_e2e_sprint14`（假说 + 包门）。

**遗留**：TODO #6 的两条路当时未点名。round-89 点名为换包。仪器状态仍是：epoch 13 全绿、包 digest `721a33d8de3a0b6e`、bar 1.0。

### Changed — 大包配对检验 + 环内查阅 + 游标停止语义（round-87，TODO #3/#4/#5 闭账）

TODO 表第 3、4、5 项落地，协议的机器部分全部接完。版本保持 1.112.0。

- **大包发布走配对检验（TODO #3）**。人换上的冻结包 val 题数 > 6 时，发布改由 `bench/compare.py` 的精确二项配对检验裁决（α = 0.05）：候选每轮 per-task 对阵 Parent 的 `per_task` 记录，**每一轮**都须「候选赢方向 + discordant ≥ 8」才发布（`paired_improvement`）。原 raw-score floors 在大包上不跑——Parent 原始分为地板时配对候选一题都输不起，检验将永远打不穿；大包的「不退化」由配对检验本身承载（每塌一题就是一张反对票，计入显著性）。候选自报 `declaration` 仍绑定且先于配对检验断言；基线缺 `per_task`（`baseline_without_per_task`）、任务集对不上（`task_set_mismatch`）、Parent 更优（`parent_better`）、discordant 不足（`not_enough_discordant`）、无显著差异（`no_significant_difference`）分别诚实拒绝，一律不动基线。5 题小包保持两遍独立求解严格高于 Parent 的旧规则不变。
- **环内查阅（TODO #4）**。enrich 阶段把 `library.load_active()` 的已发布快照渲染为只读设计上下文（`library_block`，4000 字符截断带标记）注入 dispatch prompt；候选据此查阅 Parent 线内容，而 `active` 在对比期间仍指向 Parent——只有 Accept 发布。dispatch 的 solidify state 新增 `library_snapshot` 记录本轮查阅的快照 id，对比时可证明「候选建在哪个库之上」。
- **游标接上循环（TODO #5）**。无运行中会话的 `--loop` tick 现返回 `next_action = "stop_and_report"`（`loop_stop_reason = "no_running_session"`），不写基因、不进管线；守护循环收到该判定即 break 停转，不再空转烧周期。游标提醒到期时照旧随停机报告捎带（reminder 只提醒，绝不开会话）。MCP `swarm_tick`（`is_loop=False`）不受影响。

**测试**：`test_frozen_gate.py` 增 `TestBigPackPairedCompare` 八钉（配对胜发布并推 bar、discordant 不足拒、配对回归按 `parent_better` 拒、无显著差异拒、无 per_task 拒、任务集错位拒、val id 声明保持封印、declaration 绑定）；`test_library.py` 增环内查阅四钉（enrich 挂块且不动 active、空库无块、超长截断、run record 记查阅 id）；`test_runner_loop.py` 拔「循环至少跑满一轮 GEP」旧钉（循环门后无会话 tick 根本不进管线），换「无会话 tick stop_and_report 不写基因 + 守护循环即停」与「到期提醒随停机报告捎带但仍停」两钉。受影响面 189 通过；全量回归见下。

**遗留（须步子哥执行）**：TODO #6 收口须真实运行数据——一次章程第 4 节的 Accept（提请切 minor）或八次会话无 Accept（收窄说法并关闭从未赢过的臂）；以及 round-86 遗留的 `uv run evolver anchor init --epoch 13`、真机 `evolver bench freeze` + `evolver bench baseline`。

### Changed — 焊死机器边缘 + 闭两条接缝（round-86，EvoOntology 收割）

三路侦察 EvoOntology 后落两批：**不许退化项断言**、**门入参有限性**、**验收协议冻结** 三件新机制，外加步子哥指出的两条接缝缝合。版本保持 1.112.0。

- **不许退化项断言**（收割自 EvoOntology `unacceptable_regressions`）。总分涨了但某道 val 题塌了，过去照样发布——均值看不见单题崩塌。新增 `bench/regression_guard.py`：基线现携带 `per_task`（Parent 各题自己的分，v1 格式），门在均值通过后逐题断言「候选不得低于 Parent 该题的最低复测水位」；候选可经假说的 `no_regressions` **追加**地板（只许收紧、只许引 train 题），声明格式坏、地板非有限、任一任务未测量，一律拒绝且不移动基线。
- **门入参有限性**。NaN 均值会对比任何基线都得 False，悄悄落进「持平」分支冒充惜败——现在非有限分数记 `non_finite_score` 拒绝；`load_baseline` 同样拒 NaN 标尺。
- **验收协议冻结**。基线现绑定 `anchor_epoch`（连同既有的 pack digest）：锚套件重播种（`anchor init --epoch N`）后旧标尺不得再裁判，`protocol_drift` 拒绝，Parent 须由人重测。
- **接缝一（begin_round 未接线）**。solidify 判定了候选却从未开轮：`current_candidate` 恒空、`session accept` 在门已 `accept:true` 时仍因「没有候选」失败、8 轮预算永不被消耗。现 `_settle_session` 在折账前先 `begin_round(hypothesis, candidate)`（候选 id 取 pending 周期的 mutation id，假说文本在周期焚毁前由 wrapper 先读）；轮次以 `cycle_ref`（周期 id）幂等——同一候选重试多少次只烧一轮；`rounds.jsonl` 条目新增 `cycle_ref`，`EvolutionSession.has_round_for()` 供查询。
- **接缝二（两套 id 对不上）**。`session hypothesize` 盖会话轮 id（`run_1`），solidify 核对周期 id（`run_<毫秒>_<hex>`），CLI 声明的假说必被拒。`require_for_gate` 增 `also_accept`：周期 id 与当前运行中会话的轮 id 都算「本轮」，上一周期的残留记录两条都不匹配、依旧拒绝；CLI 打印 `round scope` 帮助人确认归属。
- **E/F 批接线（步子哥解禁第 4、5 步）**。新增 `gep/library.py`（内容寻址库快照：`active.json` 只是指针、`publish` 绝不覆盖、按 id 读取不碰 active、目录名转义 `:` 以合 Windows）与 `gep/cursor.py`（`(recorded_at, session_id)` 元组比较，修对方同秒丢序之洞；**只在 Accept 推进**；reminder 只提醒绝不开会话）。会话开跑即冻结 `parent_snapshot`；`session accept` 可注入 `--snapshot` 发布快照；`--loop` 无运行中会话时不开新周期，只按 §5.5 提醒（轨迹数 ≥8 或距上次 Accept ≥7 天）。

**测试**：新增 `tests/bench/test_regression_guard.py`（14 钉）、`tests/gep/test_cursor.py`（11 钉）、`tests/gep/test_library.py`（10 钉，含 Windows 目录名冲突）；`test_frozen_gate.py` 增「单题塌了均值涨也拒」「锚重播种作废标尺」两钉；`test_paired_session_solidify.py` 增 `TestSessionLedgerFold` 五钉（拒绝开轮烧预算、重试不重烧、发布后 `session accept` 落地、会话作用域假说通行、残留记录仍拒）；CLI 拔「未装仪器即算测过」的旧钉（未冻结包 → `pack_absent` 拒绝），补「无假说拒绝」新钉。round-85 复核指出的两条接缝（`TODO.md` 第 1、2 项）就此闭账。

**遗留（须步子哥执行）**：`uv run evolver anchor init --epoch 13`（本批再触 bench/solidify 面，前值 12 仍作废）+ `anchor list` / `anchor run` 核验；真机首跑前须 `evolver bench freeze` + `evolver bench baseline` 装备标尺。

### Changed — 复核 round-85：四处已落地，两条接缝未闭

对照 `gep/frozen_gate` 实为 `bench/frozen_gate.py`、`solidify._settle_session`、`hypothesis.require_for_gate`、`evolution_session.accept` 与 instrument 第二章：

- 无基线不再自铸：`gate_verdict` 返回 `no_baseline` 且不调用 `save_baseline`。Parent 分只由 `establish_parent_baseline` / `evolver bench baseline` 写入。
- `grade_split` 在任一 val 题缺沙箱时整遍记未测量。
- instrument 已删「本场对话逐题 `bench prompt`」。评分只读已有沙箱。
- 开局预算冻在 8；`extend_budget` 拒绝 `host-agent` 及其前缀。`mechanism_check` 必须带 `before` / `after`。裸 `session accept` 没有 `accept: true` 的 `gate.json` 会拒绝。

未闭，已写进 [`TODO.md`](TODO.md) 第 1、2 项：

- solidify 记账时不调用 `begin_round`，`current_candidate` 保持空串。门已 `accept: true` 时，`evolver session accept` 仍先因「没有候选」失败，8 轮预算也不被这次固化消耗。
- `session hypothesize` 在已有会话时把 `run_id` 设成会话 id（`run_1`）。solidify 核对的是周期 id（`run_<毫秒>_<hex>`）。两条 id 对不上，这条 CLI 会把本轮假说拒掉。`swarm_hypothesis` 盖的是周期 id，那条路径是通的。

`gep/library.py` 与 `gep/cursor.py` 已经在树上，分别能存内容哈希快照、只在 Accept 时推进游标。循环还没用它们决定是否开周期。第 4、5 步仍按章程排在上面两条接缝之后。

### Changed — 配对会话治理修正（round-85，步子哥裁决后）

B′ 把门装上了，但步子哥复核出四处治理漏洞——最重的一处是**引擎在给自己发及格线**：

- **首次测量不再自铸基线**。`gate_verdict()` 无基线时 `no_baseline` 拒绝且**不写基线**；换包 `rekeyed_void` 只作废、不重建，作废的基线留在磁盘上仍绑旧 digest。旧行为的两条死局：强候选把基线抬到自己，同一改进从此永远持平；弱候选把基线压到 Parent 之下，此后回归读作「严格变好」。Parent 的分数由**不带变异的独立测量**建立——新增 `establish_parent_baseline()` 与 `evolver bench baseline`，solidify 触不到它，候选永远无法把自己写进标尺。`frozen_gate.py` 模块说明里残留的旧规则（「持平即过、未测量放行」）一并清除，免得下次修改被带回老路。
- **部分求解即未测量**。`grade_split` 改 all-or-nothing：该 replicate 里任何 val 题沙箱缺失，整遍即 `None`，不再拿已评题的平均分冒充整遍。5 题只交 1 题且恰好高于基线，过去能过，现在是未测量。返回新增 `pending_tasks`。
- **写下候选的宿主不再解 val**。密封本身早已做了（提案拒 val 题面、dispatch 与 Evidence Pack 打码），但 instrument 第二章却要求同一宿主固化前逐题 `evolver bench prompt`——题面就这么回到候选诞生的那场对话，密封与这条指令写在同一段。已删。评分只读已写好的沙箱；val 求解归属另一上下文，在那个上下文就位之前，未测量即拒绝，这是章程要的结果。
- **会话机接上 solidify**。solidify 收口时统一折账：拒绝写入运行中会话的 `rounds.jsonl` 并保持 `running`（返回体新增 `session` 字段：run_id/round/rejects/预算/状态），成功则把 `accept: true` 的门决定落盘到 `gate.json`。`session accept` 无注入门时回读该决定，**没有一份 accept:true 的门记录就拒绝**——裸 `accept` 是主张，不是测量。`test_accept_publishes_and_closes` 原先把「没有门也能 Accept」钉成成功，这颗钉子已拔。
- **假说归属本轮，且须是前后观察**。solidify 现在核对假说的 `run_id` 与本轮一致，且**门过即焚**（`clear_hypothesis()`）——上一轮的记录放行不了下一次变异。`mechanism_check` 只给题 id 不再放行：每条引用必须是 `{"id", "before", "after"}` 的重放观察（数字也认，`before: 0.0` 是真测量），裸 id 可以从包头抄来，证明不了跑过任何东西。
- **开局预算冻在 8**。`start_run` 不再收 `max_rounds`（传入即拒），CLI 撤 `--rounds`；`extend_budget` 黑名单补上实际在用的 `host-agent`（及其下划线拼写），并拒一切 host/agent/swarm/loop/evolver 前缀。instrument 不写预算调高路径。
- **锚种子探针随新契约第三次改写**（epoch 13）：no_baseline 不留痕、Parent 基线只出自独立入口、作废基线不重建、部分求解即未测量。升纪元仍须人跑 `uv run evolver anchor init --epoch 13`（前值 12 因本批再改契约而作废，**不可省 `--epoch`**）。

**测试**：`test_paired_session_gate.py` 的首测钉子改钉新契约（no_baseline 且 `load_baseline() is None`），新增 Parent 基线入口与裸 Accept 拒绝的钉子；conftest 夹具改用 `establish_parent_baseline()`，`declared_hypothesis` 增 `redeclare`；CLI 冒烟三处（预算冻 8、裸 accept 拒绝、裸 id 假说拒绝）皆按章行事。

**遗留（须步子哥执行）**：`uv run evolver anchor init --epoch 13` + `anchor list` / `anchor run` 核验。

**未动（步子哥明示）**：第 4 步内容维库快照与第 5 步游标——基线若错，快照会把错误的 Accept 发布出去，故等基线语义站稳再动。

### Changed — 配对会话 B′ 收口（round-84）

B 批把假说门与包门做对了，却漏了装门闩的另一半：**没有任何生产代码写入假说记录**。三路侦察后 `grep -rn record_hypothesis src/` 确认——生产侧只有 `memory_graph.py` 那个同名异函数（`select.py` 导入的是它），新写的 `gep/hypothesis.py::record_hypothesis` 零调用点。后果不是「无包环境停摆」，是**全环境停摆**：真实 solidify 必然 `hypothesis_missing` 被拒。本批收口：

- **宿主侧假说写入点**（§5.3）。新增闭环工具 `swarm_hypothesis`；`swarm_propose` / `swarm_solidify` 增可选 `hypothesis` 参数，记录在变异**生效之前**落盘；CLI 增 `evolver session hypothesize`（`--json` / `--stdin` / `@file`）。宿主不给假说则门照拒，**不做 fail-open**——本仓是宿主接管协议，候选「要改什么」只有宿主知晓，引擎无从代笔。
- **门序修正**：solidify 里 novelty 门与假说门对调，先验否决（这个突变根本不新）先跑，语义要求（本轮声明了什么）随后。恢复 `test_sprint23_bandit_novelty.py` 三个用例对「近重复突变不得消耗 cascade」的覆盖，顺带省掉一次 cascade 开销。
- **章程 val 题数 4 → 5**。`builtin_pack.py` 自 `3cacf45` 创建后 `git log` 零改动，val 从来是 5；漏数之由是 `spec-pipe-2` 由推导式生成（`builtin_pack.py:33`）、id 不带 `-val` 后缀，肉眼 grep 只数得 4。改文档不动包（动包会改 digest → `rekeyed_void` → 基线作废，且犯 §3/§6）。
- **锚触发面补全**：`src/evolver/bench/`、`gep/hypothesis.py`、`gep/val_seal.py` 纳入 `ANCHOR_TRIGGER_SURFACES`。此前这三个文件**从头到尾不触发锚**（config.py 清单里没有），改冻结包门全无冻结契约看守。合于仓库既有 doctrine：裁决之器亦须冻结。
- **锚种子探针改写**：`case-bench-pack-gate/probe.py` 对齐新契约（无包→`pack_absent`；首次武装→`baseline_established` 且 verdict 仍 reject；`worst>bar`→accept；flat/drop/unmeasured→reject；换包→`rekeyed_void`），`epoch_added` 提到 12。探针改用**移开**而非 `rmtree` 制造 unmeasured——冻结契约不该依赖宿主是否允许批量删除。**升纪元须人跑 `uv run evolver anchor init --epoch 12`**（不可省 `--epoch`，省略会倒挂为 1）。
- **测试侧共用夹具**：`tests/conftest.py` 增 `armed_pack`（2 val + 1 train 合成包，先答错钉基线 0.0 再答对，使下一次判定 accept）与 `declared_hypothesis`（引用 `fixture-train-1`）。`armed_pack` 返回 `rearm()` 回调——accept 会把基线抬到候选分，同一测试内第二次 solidify 否则必判 `flat`；`rearm` 只压线不判分（早先版本顺手调了 `gate_verdict()`，把本该留出的 accept 先消费了）。

**测试**：修 45 个过时断言，新增 4 个 `swarm_hypothesis` 用例。全部遵循同一判定——测成功侧的加夹具让它继续测原目标，测门本身的改断言到新契约；无删除断言、无放宽断言、无 skip/xfail。

**遗留（须步子哥执行，非代码可代）**：跑 `uv run evolver anchor init --epoch 12` 升锚纪元，再 `anchor list` / `anchor run` 核验。本机 `$EVOLVER_HOME` 未设、`anchor/` 不存在，锚当下处于「完全不跑、零保护、永远绿」状态。

**遗留（未动手，供裁决）**：Worker 报 `sqlite_store` 各函数用 `with sqlite3.connect(...)` 并不关闭连接，Windows 下 teardown 撞 WinError 32；测试侧已用 `gc.collect()` 绕过，产品侧改 `contextlib.closing` 更稳。属测试环境保健，不计入本阶段进度。

### Changed — 章程切换：配对会话

- [`演进方案.md`](演进方案.md) 改为现行章程。依据是与 EvoOntology 1.1.0 的源码对照：版本化候选、冻结会话、密封验证池、严格优于 Parent 才发布。
- 2026-09-24 外部适应度已落地的 `swarm_propose` 与冻结任务包继续有效。包门从「降分才拒绝」收紧为「未测量、持平、门异常都拒绝发布」。
- 版本仍钉 1.112.0。`EVOLVER_ACCEPTANCE_SHADOW` 保持打开。
- [`TODO.md`](TODO.md)、[`AGENTS.md`](AGENTS.md)、[`CONTRIBUTING.md`](CONTRIBUTING.md)、[`SKILL.md`](SKILL.md) 与 README 状态段已同步。

### Changed — 章程切换：外部适应度

- [`演进方案.md`](演进方案.md) 改为现行短章程。蜂群互锁视为已完成，版本仍钉 1.112.0。
- 下一阶段：重复失败走 `swarm_propose`；把 `evolver.bench` 的一个冻结任务包接进周期；约十个周期后收口。
- `EVOLVER_ACCEPTANCE_SHADOW` 保持打开。soak `ready` 不再是路线图出口。
- [`TODO.md`](TODO.md)、[`AGENTS.md`](AGENTS.md)、[`CONTRIBUTING.md`](CONTRIBUTING.md)、四种 README、[`SKILL.md`](SKILL.md) 已同步。[`RSI演进对照.md`](RSI演进对照.md) 与 [`演进方案_wikiskill对照版.md`](演进方案_wikiskill对照版.md) 改为史料，文内旧「下一步」作废。

### Added — round-82：配对会话机落地（配对会话 §5.1）

- **依据**：EvoOntology 1.1.0 `evoontology/evolution/session.py` 的会话规则。
  迁协议，不迁五类记录：会话机只认字符串 id（内容维是库快照 id，工具/图式维
  是 diff 引用）。门与发布器做成注入参数，好让状态机先独立成型。
- **新增** `src/evolver/gep/evolution_session.py`：`running` / `accepted` /
  `incomplete` 三态。预算默认 8，开局即冻结；`begin_round` 在预算用尽时把会话
  自己封成 `incomplete / budget_exhausted` 并抛
  `EvolutionBudgetExhaustedError`。Reject 只追加 `rounds.jsonl`，会话仍是
  `running`。判断性停止（`missing_data` / `unreliable_evaluation` /
  `external_block`）在 Reject 少于 2 次时拒绝封口——「还没想到新假说」不是「不
  能继续」；`user_interrupted` 与 `missing_permissions` 可立即封口。
- **只有人能加预算**：`extend_budget` 要求 `confirmed_by`，宿主侧 actor
  （host / agent / swarm / loop / evolver）一律拒绝；每次调高进
  `budget_history`（谁、何时、从几到几），可审计。
- **CLI** `evolver session start|resume|status|round|reject|accept|incomplete|
  extend|finalize`。会话目录落 `<EVOLUTION_DIR>/sessions/run_N/`，即仓外 soak
  根，产品仓不留运行态。
- **测试** `tests/test_gep_evolution_session.py` 30 项，挡住全部非法终态：已结束
  会话不可 resume / 不可开轮 / 不可决断；`finalize` 在 running 时抛；预算耗尽
  自动封口；判断性停止的 Reject 门槛；宿主加预算被拒；`accept` 无候选或门不过
  时拒绝。
- **未动**：密封 val 与包门（§5.2）、一假说（§5.3）、库快照（§5.4）、游标
  （§5.5）留给后续批次。`swarm_propose` 与冻结任务包继续有效。版本仍钉
  1.112.0，`EVOLVER_ACCEPTANCE_SHADOW` 保持打开。

### Added — round-83：密封 val 与一假说（配对会话 §5.2 / §5.3）

- **包门语义翻转**（`bench/frozen_gate.py`）：只有 val 严格高于 Parent 才
  `accept`。降分、持平、未测量、门异常、包缺失、基线作废，一律 `reject`，且
  基线不动。round-79 的「持平或提升通过」与「门不可用时降级为失效」两条作废
  ——正是这两条放过了「改测量仪器」的变异。首次 armed 只建立基线，不发布
  （第一次测量不构成「更优」）。
- **小包两轮独立求解**：val 题数 ≤ 6 时要求宿主把 val 独立做两遍
  （`--replicate=1` / `--replicate=2`），两遍均严格优于才放行。槽位落在
  `sandboxes/r1/`、`sandboxes/r2/`；`bench prompt|grade|run` 均加 `--replicate`。
- **一假说**（新增 `gep/hypothesis.py`）：每轮候选必须记录一条假说，维度限
  `content` / `tool` / `schema`（内容 / 工具 / 图式），含 `mechanism_family`、
  作用点 `target_hook`，`mechanism_check` 只许引用 train 题 id。缺记录或混入
  val id 时 solidify 在**包门之前**拒绝（`hypothesis_missing`，soft/可重试）。
- **密封**（新增 `gep/val_seal.py`）：val 题面与期望答案不得进 dispatch、
  Evidence Pack、提案回合。输出侧（dispatch / pack）计数净化并声明，输入侧
  （提案）直接拒绝（`val_seal_breach`）。train 也有的共享材料不算秘密；
  短于 6 字符的答案标 weak，不参与判定。
- **测试**：新增 `tests/test_paired_session_gate.py` 38 项、
  `tests/test_paired_session_solidify.py` 9 项。翻写
  `tests/bench/test_frozen_gate.py`（13 项）与
  `tests/gep/test_solidify_bench_pack.py`（7 项）到新契约。
- ~~**遗留待裁决**~~（三项，**已于 round-84 全部裁决并收口**）：① 包未冻结时
  solidify 一律拒绝 —— 维持严格语义、不作分层放行，45 个受影响用例改用
  `armed_pack` / `declared_hypothesis` 共用夹具回归原测目标；② 锚探针已改写
  对齐新契约，`bench/` 等三处已纳入触发面，纪元升到 12 须人跑 `anchor init`；
  ③ val 题数以源码为准改章程为 5，包一字未动。

### Fixed — round-81：包门持平分支首跑 + 通道纪律端到端针逮住真缺陷（外部适应度 #2）

- **周期**：信号族 8 accepted / 0 rejected，无 mandate。选中
  gene_stderr_channel_discipline——其策略第 1 行（paths/soak 诊断走
  stderr）round-13 已落地，本轮审计实证：七个 `--json` 动词
  （gate-report/charter-check/gene-lifecycle/soak status/variants/
  meta-report/bench gate）stdout 全部机器可解析。策略第 2 行（回归针）
  是真缺口，本轮补上。
- **变异**：新增端到端针 `test_json_verb_stdout_stays_parseable_under_
  soak_notice`——in-repo soak 路由点火（pytest 下 interlock 以
  test_environment 短路，须 patch `is_test_environment` 放行，同记忆
  「armed 模拟」条）时，`[soak] Notice` 落 stderr、`bench gate` stdout
  整体可 `json.loads`。**针落地即逮住真缺陷**：`bench gate` 未布防时
  的「gate inactive」人读提示打在 stdout，JSON 后挂尾巴（Extra data）
  ——round-80 自留的通道违规，本轮修复（提示改走 stderr，
  gene_stderr_channel_discipline 注释钉面）。测试 7→8。
- **包门持平分支首跑**：val 5/5（bench prompt ×5 重新物化→交付物→
  `bench run --no-record` 自评 1.0），solidify 包门 **pass**
  （score 1.0 vs baseline 1.0——持平即过，基线同值重写）。级联 1.0。
  事件 evt_1790258879151_68db99ca，自动提交 e650b8f。
  反馈 fb_4673dfdd9fc9。

### Added — round-80：包门生效后首个正式周期（外部适应度 #1）

- **周期**：92c615043afce17c，0.119s（hub 粘性短路生效）。Evidence Pack
  8 attempts / 8 accepted / 0 rejected——最新 attempt 为接受，mandate
  判定不触发（软提示原样渲染，PROPOSAL REQUIRED 未出现，与新语义一致）。
  选中 gene_gep_innovate_from_opportunity（intent=innovate）。
- **变异**：`evolver bench gate` 只读子命令——CLI 操作者不进 MCP 会话即可
  查包门状态（armed/pack/digest/val_tasks/baseline/baseline_digest，
  未布防时提示 freeze）。本轮 diff（cli.py + 测试针）落在章程收口判据
  点名的仪器面（acceptance/、meta_report、charter_check、
  capability_trace、测试针）**之外**——第一笔候选环外交付，是否计为
  环外增益由人在收口时判断。
- **包门首轮实跑**：宿主按新协议逐题完成冻结包 val 任务（`bench prompt`
  ×5 → 沙箱交付物 → `bench grade` 自评 5/5 满分），solidify 包门
  **established**：score 1.0，基线 1.0 持久化至 soak 根
  acceptance/bench_pack_baseline.json（绑定 digest 42bc0fcb5771bccb）。
  级联分 1.0；T0 门 shadow 判 `T0_frozen_regressed`（冻结快照滞后于
  round-79 新增测试的仪器漂移，shadow 如实记录不拦截）；锚未触发
  （本轮未触碰验证面）。事件 evt_1790257560393_65d16848，自动提交
  45fedff。反馈 fb_51e6fe843905（primary_score=1.0）。
- **发现（包缺陷，留待人工重冻）**：内建包 spec-pipe 族题面欠定——
  prompt 只说「Format product N per the pipe spec」，沙箱只有格式条款
  的 spec.txt，产品数量/状态既不在题面也不在沙箱，答案只能从包定义源码
  得知（自洽性测试直接写期望答案，绕过了可解性）。修包模板须改
  builtin_pack.py 后由人 `bench freeze --force`（改 digest=重key基线，
  章程规定为人工决定）。

### Added — round-79：外部适应度 step 1+2 落地（重复失败走提案 + 冻结任务包门）

- **Step 1（重复失败走提案）**：`gep/evidence_pack.py` 增机械判定
  `mandate`——`solidified_unresolved`（族内已落地基因但存在晚于最近
  接受的失败）或 `repeated_failure`（≥2 拒绝且零接受）时，渲染
  **PROPOSAL REQUIRED** 区块（替代原软提示，附判定原因）；instrument
  第二章同步升级为「**必须**经 swarm_propose」（自由编辑仅限新颖信号与
  结构性改动）；`swarm_tick` 结果新增 `proposal_required` 结构字段并进
  tick 摘要 allowlist（宿主不必解析提示词块即可知规则）。固化事件级联分
  原已记录（`outcome.score`，S26 诚实分），本轮把 solidify 成功返回面
  也暴露 `score`——「宿主 primary_score 来自级联或门」的机器来源闭合。
- **Step 2（冻结任务包门）**：新增 `evolver/bench/frozen_gate.py`——
  内建 12 题包经 `evolver bench freeze` 冻结至锚侧
  `$EVOLVER_HOME/anchor/bench/charter-pack.tasks.json`（环内只读；
  无 `--force` 幂等，重冻=人工决定且还原内建模板）；solidify 在验收门
  之后追加**包分门**：val 分片沙箱确定性评分，低于基线（上次接受分）
  即拒绝回滚（`bench_pack_rejected`；failure_mode=soft/retryable，
  循环继续换路）；持平或上升通过并推进基线；首轮 establish；
  unmeasured（沙箱缺位）不表态不推进；基线绑定包 digest（改规则=
  rekey，记录在案）；门侧故障降级 inactive 绝不碰 solidify。失败路径
  单次追加事件并显式挂 DGM 变体档案与诊断条目钩子（不 replicate
  fitness 拒绝路径在 `enable_failure_events` 默认开时的双写）。
  事件与返回面均携 `bench_pack` 证据。锚种子新增
  `case-bench-pack-gate` 探针冻结门语义。
- **Fixed（存量，DEBUG #46）**：round-77 契约变更未同步锚探针模板
  （`case-gate-calibration-invariants` 假 subprocess 缺 `returncode`），
  种子套件在干净树上红并被带过两轮；本轮补齐并以新探针冻结包门契约。
- **测试**：mandate +9、冻结门 +12、solidify 接线 +7、CLI freeze +2、
  swarm 字段/instrument +3；全量 3793 passed（25 slow deselected），
  ruff/mypy 归零。真机已 `bench freeze`（digest `42bc0fcb5771bccb`，
  5 个 val 任务），下一轮固化起门生效。

### Fixed — round-77（续）：stale 冻结 ID 致整 chunk 归零的假杀根因修复
- **根因**：冻结快照含 6 个 stale ID（round-71 测试改名遗留）→ pytest
  对含不存在 ID 的 chunk 返回 **rc=4 且整个 chunk 不运行** → 400 测试
  计零 + 基线已知失败 1 = 401 → candidate 0.890227（rounds 73/74/75
  三连 identical）。三轮 shadow 假杀全部由此解释。
- **`acceptance/t0_frozen.py`**：rc=4 时从 stderr 解析 not-found ID、
  从 chunk 剔除后**重跑一次**——幸存者被测量；stale ID 计 failed
  （删除冻结测试=回归，保留 test_gate_missing_ids 契约；初版曾错把
  stale 记 passed，已回滚为 failed 语义）。语义修正：rc=4 重跑不与
  超时重试混用（stale ID 重试必然复现 rc=4）。

### Added — round-75：P2-7 写侧接线——失败漏斗自动开诊断条目
- **`gep/solidify.py`**：`_maybe_open_diagnostic_entry` 接进
  `_append_failure_event` 共享漏斗（与 variant archive 同钩、同
  never-raises 契约）——失败阶段命令名 → 嫌疑组件、stderr/stdout
  尾部 → 症状文本；空症状不开条目。round-74 数据面自此有生产写侧。
- 两测：失败开条目（suspect_components 含 mypy、hypothesis 空=宿主
  后填）+ 账本路径损坏不断事件流。

### Added — round-74：P2-7 跨组件诊断账本——DEBUG.md 方法论代码化（RSI P2 第二交付）
- **`gep/diagnostic_ledger.py`（新）**：`symptom_signature`（失败末行
  去易变后缀 sha256 短哈希——同缺陷跨 run 稳定）、`open_entry`
  （solidify 验证失败自动开条目，**同签名复发递增 recurrence 而非
  追加重复**——复发即 P1-4 证据包的检索信号）、`backfill_attribution`
  （修复落地后宿主回填 hypothesis/blamed_component/resolved）、
  `find_similar`（trigram 相似度检索历史归因，同签名复发不再人工翻
  DEBUG.md）。
- **边界厘清**：诊断账本检索**归因记录**（signature/归因组件），
  变体档案检索**编辑指纹**——互补不重叠。接线（solidify 失败漏斗）
  留下一轮与消费端同轮设计。
- 九测：签名稳定性/异缺陷异签名/开条目/复发递增/backfill 语义/
  未知签名/相似检索/不相干不检索。

### Added — round-73：P2-10 能力轨迹图——soak 报告 v2 首节（RSI P2 首个交付）
- **`ops/capability_trace.py`（新）**：`capability_trajectory` 纯函数
  ——HCI 归一化余量地图：gated_cumulative / anchor_cases /
  env_headroom（反向：少用 env 预算=进展）三维各自 now/target →
  0-100（clamp），overall 为均值（无隐藏权重）。目标值镜像章程
  （40 gated / 16 探针 / 20 env headroom）。
- **`ops/charter_check.py`**：报告增 `capability_trajectory` 节 +
  文本条形图渲染（`|##########| 70%`）。**严格分离**：余量图纯观测
  ——全绿轨迹不得暗示转正就绪，verdict 语义仍由 soak recommender
  独裁（尾注明示 "not a promotion signal"）。
- live 渲染：gated 100% / anchor 100% / env headroom 10% → Overall
  70%。锚实弹 16/16（charter_check 触发面）。

### Added — round-67：population CLI 败者入档契约钉面（round-41 覆盖缺口）
- **缺口**：`_cmd_solidify_population` 是 5 函数协作组装
  （run_population→solidify→classify_rejection→append_candidate_jsonl）
  ——模块级函数各有单测，但**端到端败者路径零覆盖**。
- **`tests/test_recent_rounds_cli.py`**：
  `test_loser_archived_with_sibling_lineage`——完整 `--population`
  流程断言败者条目入 candidates.jsonl：`population_status=rejected`、
  `sibling_of=胜者 run_id`、`rejection_class=semantic`（夹具的
  validation detail 形状对齐 `_run_validations` 输出——首版漏 detail
  即红，正是被测契约的实现细节暴露）。纯测试轮零源码改动。

### Added — round-66：gene-lifecycle JSON 视图对等（round-58 契约补齐）
- 文本视图（near-miss 段）有断言但 JSON 视图（webui/脚本消费面）无
  覆盖——`test_cli_gene_lifecycle_flow` 同 fixture 增 JSON 断言
  （`approaching.threshold=3` + candidates 含 gene_alive）。**程序化
  消费面与文本面是一等契约的两面**——只钉文本留下机器可读契约无
  看守。纯测试轮零源码改动。

### Fixed — round-65：TTL 重探语义修正——降档+折半递增（round-59 重探暴露）
- **两处设计缺陷**：(1) sticky 态下的重探 fetch 以**首探完整重试预算**
  执行（3.9s）——已知 404 端点不该享受首探待遇；(2) 重探失败后 TTL
  **完全重置 24h**——端点连续 5 次 404 横跨多日，每次重探都把下次
  重探推后一整天。
- **`gep/hub_health.py` + `evolve/pipeline/hub.py`**：
  `HUB_404_REPROBE_FLOOR_S=1h`（折半下限）+ `reprobe_count` 记账 +
  `endpoint_sticky` 折半等待语义（24h→12h→6h…→1h）——持续死亡的
  端点重探频率收敛，回归端点仍在一个窗口内被捕获；重探 fetch 降档
  为单发；成功/非 404 双清零。
- **教训**：粘性态的重探不该用首探预算；测试引擎正确粘住行为后再
  断言最终重探（失败的重探会刷新 last_probe_ts，下周期正确粘住——
  测试需先老化时间戳）。

### Changed — round-64：跨面板别名注记（retention↔library 同数异名）
- **发现**：meta-report 中 retention 面板 `signal_recurrence_free`
  =25/43 与 library 面板 `resolution` =25/45 两数恰等、命名反向
  （recurrence_free=好 / resolved=好）——查码证实**同源**（landing
  统计同一 resolved 计数），但操作者无法不查码区分「同口径两措辞」
  与「两种计算」。
- **`ops/meta_report.py`**：retention 面板增 note 显式标注别名关系。
  **加法优于改名**——既有键契约（tests/webui 消费者、锚探针字典
  精确相等断言）优先于命名优雅；纯增量键实测 40 passed 含 epoch 4
  探针。

### Fixed — round-63：cleanup 触发面补课（#38 教训追溯应用）
- **`config.py`**：`ops/cleanup.py` 入 `ANCHOR_TRIGGER_SURFACES`——
  `cleanup_run_directories` 持 evidence/ run 档案的**删除权**：删除权
  是**否决权的破坏性等价物**（`max_dirs` 改大=无界增长回归；改小=
  诊断证据过早丢失）。round-56 以「无否决权」跳过守护是判定失误，
  追溯修正。守卫测试双向钉面。
- 无探针语义变化故不升 epoch（16 探针不变）；扩面生效的实弹验证
  留待未来首个触碰 cleanup.py 的变异。
- 插曲：首次 solidify 被会话取消中断（无 stash 残留、工作树变异
  完整保留），重新派发后重固化绿；gene_destructive_twin_guard 的
  lineage 挂在旧 run 的 distill（分裂如实记档）。

### Added — round-62：effective-L5 复跑 #5（RSI §6.9，挂钟条款）
- 纪元 E''（rounds 55-62 尾段，9 事件 8/1）——**首个 near-catch 生产
  事件**：round-57 stale needle 被**老级联**诚实拒绝（真阳性，非新
  机制解锁故不计判据 (a)）；「拒绝→修复→重派→接受」与 DGM 同形但
  经 stash 非档案——修复改变 diff 本身，指纹重派前提不适用（档案
  语义=同一编辑环境修复后重试）。
- 拒绝分型学第三类：**文本卫生类**（stale assertion——ruff/mypy
  覆盖不到，只有 pytest 逮）；精确度 B 起 9/10；零拒绝连续段打破=
  验证器安静期不沉睡的生产证明。
- 修复-等待-兑现弧第三例：round-53 超时校准 → round-59 TTL 重探
  3.2s live 验证。维持 2/3；复跑 #6 ~round-72 或捕获入账。

### Added — round-61：distill→propose 最小桥（S29 通道采用缺口）
- **诊断**：S29 机械提案通道自 round-32 落地生产仅 2 次调用（测试期）
  ——**采用缺口而非能力缺口**（门在、锚守卫在、population 消费者在，
  自由执行→distill 主路径从不途经结构化通道）。
- **`swarm.py`**：`_extract_proposal_candidates`——distill 的
  response_text 中 fenced ```json 块若解析为 GeneProposal 形状
  （action + edits）则作为 `proposal_candidates` 随结果返回（含
  `proposal_next_step` 指引）；**观察不应用**——重放仍须过同一验证
  门；格式变体静默跳过（桥不得把格式偏差变成宿主错误）。为 K=2
  首轮提供机械候选源。

### Fixed — round-59：cleanup 死接线闭合 + TTL 重探生产实证
- **发现**：round-56 的 evidence 轮转在生产形态下是**死代码**——唯一
  调用方是守护循环每 10 周期清理，但 CLI 单周期/MCP tick/solidify 从
  不调 `run_cleanup`，且唯一在跑的守护进程（Sep 7 启动）是 round-7
  时代代码、没有该函数。
- **`evolve/post_cycle.py`**：轮转接进每周期路径（与 gene lifecycle
  同位置，目录列举成本可忽略）。**实证**：接线后首次 dispatch soak
  evidence 25→**10**（稳态有界）。
- **附带生产实证**：TTL 24h 重探兑现——重探周期 hub=3.19s（counter
  3→4，落在 round-53 新 5s/10s 天花板内——超时校准 live 验证），后续
  周期恢复跳过。
- **教训**：修好的东西要问谁在生产形态真的执行它（守护的代码年龄、
  单周期路径覆盖面都是审计对象）；维护性工作接每周期路径当成本可忽略。

### Changed — round-58：gene-lifecycle 近阈值段（P1-5 生产零转移的操作者面收口）
- **结构事实**：soak 实测 39 个落地基因 **0 个达到观测阈值 3**（最高
  2）——每轮蒸馏落地新基因（`landed_gene_ids` 口径），被再选中的旧
  基因不带 landed（`faithful_use` 的 gene_id 口径）——P1-5 状态机的
  观测人口=「同一基因作为新知识落地的次数」，本循环形态下结构性
  罕见（与捕获罐同构：机制落地≠有效证据）。
- **`cli.py`**：`_lifecycle_approaching()`——`gene-lifecycle list`
  空记录时渲染 near-miss 段（obs/landings/resolved，与状态机同源
  `landing_stats`）；JSON 输出增 `approaching` 字段。阈值不调
  （无证据不调参——章程纪律）。
- **教训**：阈值门控的状态机生产零转移时必须说 WHY 并展示多近；
  空态渲染与状态机同源统计。测试夹具注意：无后代的落地观测=0
  （「沉默不是证据」语义）。

### Fixed — round-57：MCP 注入提示词三缺口——初始化即可用（用户任务）
- **审阅结论**：注入三通道按保证级分层——instructions（initialize
  必达）> `evolver_swarm` prompt（宿主选渲染）> `swarm_boot` 工具
  （宿主选调用）；attend 模式下完整协议只经后两者到达，prompt-less
  宿主只有前者。
- **`mcp_server.py`**：instructions 从「指针段」升级为**自足
  bootstrap**——祈使首动作（调用 `swarm_boot` 拿完整协议+实时状态+
  正确下一步）+ 完整功能地图六组（自动进化闭环五步+propose / 只读
  状态面 / 治理 supervise+approvals / hooks 双轨 / workflows / 多节点
  邮箱+skills）+ `evolver://*` 资源 + 稳态守卫语义。AUTO_HIJACK 强制
  前缀与 attend 建议性保持不变（章程纪律）。
- **`swarm.py`**：(1) `swarm_boot.next_action` **pending 感知**
  （`swarm_solidify` if pending——round-4 只修了 prose 漏了结构化
  字段，读字段的宿主拿错首动作）；(2) instrument 第六节补
  **supervision / hitl** 行（状态早已返回但从未渲染——宿主首 tick
  前可见暂停/否决）。
- 16 needle 钉面（`test_instructions_are_self_sufficient_bootstrap`）；
  同步三处指令断言（单测/E2E/协议 E2E——级联首拒抓到第三处 stale
  needle）。**教训：指令按保证级分层，完整指引属最高保证通道；
  结构化字段与 prose 分支同源派生。**

### Fixed — round-56：evidence/ 死写者收编——有界轮转（零读者存储泄漏）
- **发现**：`gep/evidence.py` 的 `save_evidence` 每次 solidify 落盘
  ~14KB/run，但 `load_evidence` **全仓零生产消费者**（仅测试引用）；
  cleanup 轮转不覆盖该目录——只写不读只涨不删（soak 侧 22 目录
  428K、repo 侧 30 目录，无限增长）。
- **`ops/cleanup.py`**：`cleanup_run_directories`——mtime 降序保留
  最新 `CLEANUP_MAX_FILES` 个 run 目录，接进 `run_cleanup`；docstring
  记录决策依据与重访条件（接读者须重开窗口）。
- **教训**：零读者的写侧是穿着功能外衣的无限增长——grep 消费者
  先于尊重写者；三选项显式权衡（接读者/删写入/轮转收编）。

### Added — round-55：近四周改动回溯测试覆盖（rounds 27-54，13 新测）
- **`tests/test_recent_rounds_cli.py`（新）**：五类缝钉面——路由白名单
  成员**双侧契约**（写者/读者在集、gate-report/charter-check 双视图
  命令留在外）；round-53 超时校准值（10s/5s）+ floor 余量下限 +
  sticky 常量（3/24h）不变；round-47 unverified reason 四要素
  （工件/路径/行格式/登记条件）；variants CLI 四测（含 re-dispatch
  真实应用到沙箱 git 仓库）；round-41 `--population` 接线（胜者传递、
  败者不落地）；round-49 soak status 渲染行。
- **`cli.py`**：路由白名单提升为模块级 `SOAK_ROUTED_COMMANDS`
  （frozenset 26 命令）——静默删除即红。
- **覆盖测试抓到真缺陷**：round-44 re-dispatch 参数接线只收裸 id
  形式，文档形式 `variants re-dispatch <id>` argparse 报「多余位置
  参数」——重接线为 action/variant_id 双位置参数 + 兼容旧裸 id 形式。
  **教训：测试写不出来时先怀疑接口——文档形式可能根本 parse 不了。**

### Fixed — round-54：运行态状态盘查——conversation_sniffer 泄漏（#37 家族第五例）
- **盘查方法**：30 个 `get_evolution_dir()` 写入模块逐个过测试隔离 refs，
  不等泄漏自曝。坐实：`conversation_sniffer_state.json` 在仓内存在且
  `last_sniff_ts` 随测试运行递增——try_sniff enforce 模式找到 candidates
  即无条件 `_write_state`，泄漏测试 161 行 `cs.read_state()`（真实路径）
  + 真实证据直写仓内。
- **`tests/conftest.py`**：autouse `_isolate_sniffer_state`——monkeypatch
  `_state_path` 指向每测试 tmp（round-48 同教义，无条件重定向）；残留
  清理后零泄漏复验。盘查结论：无第六处（其余写入模块由既有套件覆盖）。
- **教训**：绿套件对静默状态写入无发言权——按写入模块清单主动盘查，
  用 mtime/content 变化跨绿跑证明清洁。

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
