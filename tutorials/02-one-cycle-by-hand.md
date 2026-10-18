# 第二讲：亲手转一圈齿轮——从报警到入库的七步

上一讲我们看清了四样零件：报警信号（Signal）、菜谱卡片（Gene）、成功留样（Capsule）和门口保安（Solidify）。

这一讲我们来看看，当你敲下 `uv run evolver run` 的时候，引擎内部到底发生了什么。

很多人以为敲下 `evolver run`，引擎就会自己去连 OpenAI 或者 Claude，噼里啪啦把你的代码改掉。
**错。它根本不连任何大模型。**

单周期的 `evolver run` 干的事情非常纯粹：它把你的工作区彻底检查一遍，挑出最该修的问题，选好对应的基因卡片，最后**吐出一份写得严丝合缝的“派工单”（GEP 提示词）**。至于拿着派工单去改代码，那是执行器（你自己，或者第三讲要说的 MCP 宿主）的活；改完之后，再调 `evolver solidify` 请保安验货。

为什么非要把“出派工单”和“改代码”劈成两半？因为一旦合在一起做成黑盒，出了错你都不知道是问题找错了，还是代码改歪了。

---

## 一圈齿轮是怎么转的？

每次跑一个周期，引擎手里都端着一个大托盘——代码里叫 `ctx`（就是一个普通的 Python `dict`）。这个托盘依次经过 **起飞前安检（Preflight）** 和 **七个工位（Pipeline）**，每个工位往托盘里放几样东西：

```
[起飞前安检] ──▶ 1.Collect ──▶ 2.Signals ──▶ 3.Hub ──▶ 4.Enrich ──▶ 5.Autopoiesis ──▶ 6.Select ──▶ 7.Dispatch
```

我们跟着托盘走一趟：

### 0. 起飞前安检（`guards.py`）
飞机起飞前要先看油够不够、跑道滑不滑。
安检员会查三件事：系统负载是不是爆了？内存（RSS）是不是快溢出了？距离上次运行是不是还在冷却期？
如果安检没过，直接拉闸中止（Abort），并且把这次中止记进 `autopoiesis_preflight_abort.json`——下个周期一起来，第一件事就是处理上次为什么没飞起来。

### 1. Collect（翻垃圾桶找线索）
第一个工位去翻 `memory/` 目录下的运行日志、最近的进化事件、上次没跑完的任务，把原始文本捞进托盘。

### 2. Signals（贴报警标签）
第二个工位拿着正则和规则看刚刚捞出来的日志：
- 看到报错栈？贴上 `log_error`。
- 看到同一个错连续出现？贴上 `recurring_error`。
- 看到上次评测分数掉下去了？贴上 `swarm_feedback:degraded`。
托盘里多了一串去重后的信号列表 `signals`。

### 3. Hub & 4. Enrich（查外援与翻老账）
如果配了远端 Hub，去问问有没有别人共享的好基因；同时在本地翻翻记忆图谱（`memory_graph.jsonl`）和活记忆（`LESSONS_LEARNED.md`），看看以前遇到同样的信号时，哪张基因卡片最管用。

### 5. Autopoiesis（自检与防呆规则）
这个词看着吓人，干的事却很实在：引擎给自己量体温（看最近的成功率、回滚率、连败次数），同时把之前踩过的坑变成自动守卫规则（`autopoiesis_rules.json`），塞进托盘提醒后面的工位别重蹈覆辙。

### 6. Select（挑卡片，还要防“老油条”）
现在托盘里有了信号，选卡员（`selector.py`）去基因库里挑最匹配的 `Gene` 和 `Capsule`。
这里有个很妙的细节：**如果某张基因卡片连续被选了 8 次，每次都什么改动也没做（惰性基因），或者刚刚才用过，选卡员会给它扣分甚至禁选**（`gene_lifecycle.py` 还会把长期零效果的基因打入 `under_review` 直至 `retired` 退休）。这防止了引擎在一张废卡片上死磕到底。

### 7. Dispatch（打印派工单 + 收集历史失败证据）
最后一个工位（`dispatch.py` 与 `prompt.py`）把前面所有东西汇总，印出一份 GEP 提示词。
注意！在给你推荐基因卡片之前，它会先通过 `evidence_pack.py` 印出一份 **证据包（Evidence Pack）**：
> “警告：在这个信号族下，过去已经试过 3 次修改，其中 2 次因为 pytest 挂掉被拒，已试过的改动指纹是 xxx，千万别再原样试一遍！”

这就叫**证据先于建议**。先让你看清以前是怎么死的，再告诉你这次建议怎么改。

---

## 守门员 `solidify` 是怎么防闯祸的？

派工单印出来了，代码也改完了。现在你敲下 `uv run evolver solidify`。守门员（`gep/solidify.py`）按顺序做下面几步，一步不对立刻回滚：

1. **先备份现场**：在动任何东西之前，先把当前工作区状态存好（默认走 `git stash` 策略）。万一后面炸了，一秒钟恢复原状。
2. **查假说门（`hypothesis.py`）**：如果你在配对会话里，必须先声明“我这次改了什么、为什么觉得能过、预计哪些检查会过”。不写假说就想闯关？门都没有。
3. **算爆炸半径（Blast Radius）**：用 `git status` 和 `git diff` 算一下你到底动了几个文件、多少行代码。
   - 动了 `.git` 或禁区路径？拒！
   - 基因要求最多改 5 个文件，你改了 8 个？拒！
   - 什么文件都没改（空跑）？记一笔零工作量，不发奖章！
4. **在隔离环境跑验证级联**：跑基因里写的 `validation` 命令（而且默认在独立的 Git worktree 里跑，防止测试过程中产生的临时文件弄脏你的主目录）。
5. **结算并记入 Episode**：无论通过还是被拒，在周期结束的这一刻，引擎都会把“你改了啥 diff、跑了啥测试、报了啥错、过了哪道门”原原本本写进一张不可篡改的过程档案——**Episode Record**。

---

## 🔨 动手验证（2 分钟）

我们用一个完全隔离的临时目录，亲眼看看“打印派工单”和“基因选择”是怎么运作的：

```bash
uv run python -c "
import asyncio, tempfile, os, io
from contextlib import redirect_stdout
from pathlib import Path

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['OPENCLAW_WORKSPACE'] = tmp
        os.environ['EVOLVER_REPO_ROOT'] = tmp
        os.environ['EVOLVER_SOAK_ALLOW_INSIDE'] = '1'
        os.environ['GEP_ASSETS_DIR'] = str(Path(tmp) / '.evolver' / 'gep')
        os.environ['EVOLUTION_DIR'] = str(Path(tmp) / 'memory' / 'evolution')
        os.environ['A2A_HUB_URL'] = ''
        log_file = Path(tmp) / 'memory' / 'evolution' / 'pipeline_events.jsonl'
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text('Traceback: ImportError: cannot import name parse_duration\n' * 4, encoding='utf-8')

        from evolver.evolve.runner import _run_single_cycle
        with redirect_stdout(io.StringIO()):
            ctx = await _run_single_cycle()
        print('1. 捕获到的信号:', ctx.get('signals')[:3])
        gene = ctx.get('selected_gene') or {}
        print('2. 选中的基因卡片:', gene.get('id'), '| 类别:', gene.get('category'))
        print('3. 派工单长度:', len(ctx.get('gep_prompt') or ''), '字符')

asyncio.run(main())
"
```

仔细看终端打印出来的三行结果：
1. 你在日志里写了一行 `ImportError`，**Signals** 工位立刻抓到了 `errsig:Traceback: ImportError...` 和 `log_error`。
2. **Select** 工位一看有报错，自动挑中了 `gene_gep_repair_from_errors`（`repair` 修复型基因）。
3. **Dispatch** 工位生成了一份数千字符的 GEP 变异提示词。

全过程没有调任何外部大模型，没有任何黑盒魔法。就这么回事。

👉 **[下一讲：蜂群接管——为什么引擎自己不调大模型？](./03-swarm-and-host-takeover.md)**
