# Mimosa 深扫 triage（2026-09-17）

> 扫描：`scan-2026-09-17T07-16-18.936Z-0656e7af67ff`（deep，
> seal `sha256:3c61f7e9…49bc8948`，25 findings，证据边界
> `static_only_no_runtime_execution`）。原始报告在
> `~/.mimosa/security-scans/project-447b905a1785898995436aa9/`。
> 威胁模型前提：evolver 是**本地单用户 CLI 引擎**——配置/env/命令行
> 由操作者本人控制；"攻击者"指能影响运行态数据（hook payload、
> Hub 派生文本、日志内容）但不控制 env/模板的远程或半信任来源。

## 判定总表

| # | 类别 | 位置 | 判定 | 依据 |
|---|---|---|---|---|
| 1 | 资源所有权 | proxy/server/routes.py:870 | by-design（记录） | `/task/*` 是本地内存状态机，非生产任务流（AGENTS.md 已声明非 Hub 生产级）；转正生产化时需补租户绑定 |
| 2 | 代码注入 | gep/hub_review.py:106 | 误报 | `subprocess.call` 等是审查器自身的可疑模式串（检测器，非执行器） |
| 3-4 | 代码注入 | gep/validator/sandbox_executor.py:253-254 | 误报 | 同上：沙箱 blocklist 字符串字面量 |
| 5 | 命令注入 | cli.py:1753 | by-design | `evolver exec` 执行操作者自己的命令（本地手动子命令，操作者=信任根） |
| 6 | 命令注入 | gep/llm_template.py:80 | **真实（潜伏）→ 已加固** | 见下节 |
| 7-11 | 不安全随机 | mutation.py:137 / selector.py:219,270 / mailbox/store.py:87 / scripts/self_ab_acceptance.py:78 | by-design | 选择/抖动用途，非密码学 |
| 12-22 | 路径穿越 ×11 | curriculum / feature_flags / issue_reporter / open_pr_registry / question_generator / skill_distiller / skill_publisher / validator/reporter / validator/stake_bootstrap / ops/cleanup / mailbox/store | by-design | 全部是配置/env 驱动的路径拼接（操作者控制根路径的本地工具语义）；无远程输入直达 join |
| 23-24 | SSRF | gep/mailbox_transport.py:37 / gep/reuse_attribution.py:156 | by-design | 出站到操作者配置的 Hub 端点（`A2A_HUB_URL`），非用户输入构造 URL |

## 唯一真实项：llm_template 原始占位符注入（round-29 加固）

`run_external_template` 把占位符值替换进 `shell=True` 命令串执行。
`render_template` 的设计只防 ARG_MAX（`{<name>_file}` 机制），未防
注入：值含反引号或 `$(` 即命令替换执行。当前**零生产调用方**
（`enable_llm_template` 默认关、无模板配置），但模块是文档声明的
B1/C2 LLM 调用机制，接线后占位符值将含诊断 prompt（运行态日志与
Hub 派生文本）——半信任输入直入 shell。

**加固（fail-safe，零新 env 旋钮——soak 章程纪律）**：被原始替换
进模板的占位符值含命令替换构造（`` ` `` / `$(`）即拒绝执行，落
`_refused.txt` 审计标记并返回空串（与 timeout/OSError 同契约）；
拒绝消息指向 `{<name>_file}` 占位符（自由文本载荷的正道）。模板
自身的 shell 语法不受限（操作者信任根）；经 `_file` 机制传入的值
不检查（入命令的是引擎生成的路径）。

## 遗留观察

- hook 的 `scanner_enobufs` 提示与已完成扫描并存（缓存不同步），
  本文档即完整审计的落账。
- 本 triage 是静态候选的人工判定，**不构成项目安全声明**。
