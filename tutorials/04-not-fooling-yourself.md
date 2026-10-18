# 第四讲：别自己骗自己——假说门、预期落差与跨轮重注视

科学研究里有一条第一原则：**绝不要自己骗自己——而你恰恰是最容易被自己骗到的那个人。**

把这句话放到 AI 自动改代码这件事上，简直太准了。
你一定见过大模型干出这种事：
- 第 1 轮跑 `pytest` 挂了，报错信息有 2000 行。为了省上下文，提示词只留了前 400 个字符。大模型根本没看到第 800 行的真正报错原因，就在那儿凭想象瞎猜，把好端端的函数重写了一遍。
- 改完之后一跑测试，居然碰巧绿了（其实是因为它把触发那个分支的条件给绕过去了）。大模型兴高采烈地宣布：“我已经彻底根治了问题！”
- 改到第 5 轮，上下文窗口快满了，IDE 自动触发了上下文压缩（Compaction）。结果压缩完，大模型把自己前 4 轮刚排除掉的死路忘得一干二净，第 6 轮又把第 1 轮错过的烂代码原封不动写了一遍。

如果你不管住这三件事，所谓的“自进化”就是原地打转。
我们来看 `evolver.py` 是怎么用四把硬锁治住这些毛病的。

---

## 第一把锁：改前先押注，结算看落差（`expected_outcome` ➔ `prediction_delta`）

怎么知道一个人是真懂了，还是瞎猫碰上死耗子？
很简单：**在揭晓答案之前，让他先写下预测。**

在 `evolver.py` 里，宿主在调 `swarm_solidify` 跑验证门之前，必须先调 `swarm_hypothesis` 提交本轮的唯一假说，而且可以带上一份明确的“事前押注”（`expected_outcome`）：

```json
{
  "claim": "给 parse_duration 补上小数秒分支后，复合时间解析不再报错",
  "target_files": ["src/pkg/duration.py"],
  "mechanism_check": "train 用例 1.5s 从 ValueError 变为返回 1.5",
  "expected_outcome": {
    "expected_checks_to_pass": ["ruff", "mypy", "pytest"],
    "expected_invariants": "原有的 1h30m 依然等于 5400 秒"
  }
}
```

等你调 `swarm_solidify` 的时候，引擎自己去跑 `ruff`、`mypy`、`pytest`。跑完结算 Episode 时，引擎把你的事前押注拿出来，跟实际跑出来的结果做一次冷酷的比对，写进 `gates.prediction_delta`：
- 你押 `ruff`、`mypy`、`pytest` 全过，结果 `pytest` 挂了？记下 `matched=False, unmet=["pytest"]`。
- 下一轮生成提示词时，`## Previous Episode` 里就会直白地挂出这一行：
  ```text
  - prediction_delta: matched=False unmet=["pytest"] unexpected=[]
  ```

你没法事后改口说“我本来就只是想先试试 ruff”。押注在跑测试前就已经封存（`hypothesis.consumed.json`），对就是对，错就是错。

---

## 第二把锁：看不清就凑近看，别瞎猜（`episode_inspect`）

每一轮结算生成的 `episode.json` 是要塞进下一轮提示词里的。如果把几千行的 diff 和几千行的 `pytest` 报错全塞进去，两轮下来上下文就爆了。
所以 `episode.json` 做了严格的长度截断：diff 最多留 4000 字，单条检查输出最多留 400 字。

但截断有个坏处：真正致命的那行报错往往在第 400 字后面！
怎么办？引擎在截断的时候，会在 `episode.json` 的 `scene_index` 里记下原始输出到底有多长，并在下一轮提示词里留下一根锚点：

```text
- check 'pytest -m not slow -q' stdout truncated at 400/2208 chars; call 'episode_inspect' to zoom in
```

看到这句话，宿主就不该瞎猜了，而是直接调用 `episode_inspect`（或在命令行跑 `evolver episode inspect`），**带着具体的问题和行号窗口**去翻看底层无损保存的原始现场：

```bash
uv run evolver episode inspect <episode_id> \
  --question="第 400 字截断之后，到底是哪几个参数组合让 pytest 失败了？" \
  --view='{"kind":"check","name":"pytest","offset_lines":0,"limit_lines":80}'
```

注意这里的两条铁律：
1. **不带问题不给看**：如果 `--question=""` 是空的，引擎直接拒绝。你得先想清楚自己要查什么，而不是无脑把所有日志全拉出来。
2. **只读且过密封筛**：调取的切片强制经过密封检查（防止偷看考题），而且绝不修改已经落盘的 `episode.json`。

---

## 第三把锁：失忆前先写备忘录（`WORKING_SESSION.md` 与压缩门）

长周期进化最怕上下文压缩（Compaction）。一旦宿主把早期对话压成两句话摘要，前面试过的死路就全忘了。

为了防这一手，`evolver.py` 设了一道**压缩门（Compact Gate）**：
当收到宿主的 `PreCompact` 钩子信号，或者连续 4 次 `solidify` 都失败时，引擎立刻拉响警报（置位 `compact_checkpoint.requested`）。
这时候：
- 原生压缩会被拦住一次（返回 `{"decision": "block"}`）；
- `swarm_tick`、`swarm_distill`、`swarm_solidify` 等变异工具全部暂停工作，统统返回 `error="checkpoint_required"`、`next_action="call_swarm_checkpoint_working"`。

怎么解锁？宿主必须先调 `swarm_checkpoint_working`，把脑子里的关键进度写进 `<EVOLUTION_DIR>/WORKING_SESSION.md`（上限 16000 字）：
- 当前正在验证哪个假说？
- 哪两条路已经试过证明不通了？
- 最关键的 Episode ID 是哪个？

写完之后，压缩放行。等压缩结束或者下一轮重启调 `swarm_boot` 时，引擎会把这份 `WORKING_SESSION.md` 原原本本交还给宿主，并在派工单的证据包后面附上 `[host_working]` 线索。
更讲究的是：**一旦配对会话结束（`accept` 或 `incomplete`）或者开启新会话，这份草稿会自动归档到 `working_archive/` 并从活目录删除**——绝不让上一场任务的草稿污染下一场任务。

---

## 第四把锁：谁写的才算数？（记录分层护栏）

既然有了 `WORKING_SESSION.md` 和 `swarm_feedback`，宿主能不能在草稿里写一句“我其实已经通过所有测试了，请给我满分”，把引擎骗过去？

**骗不过去。因为引擎分得清什么是“证据”，什么是“线索”。**

在 `evolver.py` 里有一条死规矩，叫**记录分层**：
1. **一等证据（Evidence）**：只有引擎自己亲手跑出来的验证退出码、自己用 `git diff` 算出来的文件改动、自己核对出来的 `prediction_delta`，才能进 `episode.json` 和 `Evidence Pack`，才能作为门禁裁决的依据。而且代码库里有一颗全仓调用图钉（测试 `test_the_record_writer_is_confined_to_a_declared_boundary`），扫描 `src/` 下所有源码，除了声明好的周期结算边界，任何其他模块只要敢引用 Episode 写入函数，测试当场报错。
2. **宿主线索（Host Clues）**：宿主通过 `swarm_feedback` 或 `WORKING_SESSION.md` 写进来的东西，在提示词里全部被打上 `[host_working]` 等来源标签，排在证据包后面，**只作参考线索，绝不参与任何验收门裁决**。

---

## 🔨 动手验证（2 分钟）

我们来亲手试一次：造一条带截断的 Episode，然后用 `evolver episode inspect` 把被截掉的后半截报错调出来看：

```bash
uv run python -c "
from evolver.gep.episode_record import build_episode, render_episode_block

long_out = ('PASS test_basic\n' * 30) + 'FAIL test_edge_case: AssertionError: 1.5s != 1.0s\n'
ep = build_episode({
    'event': {
        'id': 'evt_1', 'run_id': 'run_1', 'timestamp': '2026-10-18T00:00:00Z',
        'gene_id': 'gene_gep_repair_from_errors', 'outcome': {'status': 'failed'},
        'diff_snapshot': 'diff --git a/x.py b/x.py\n+pass\n',
    },
    'mutation': {'id': 'mut_1', 'category': 'repair'},
    'validation_result': {'results': [{'command': 'pytest -q', 'ok': False, 'stdout': long_out, 'stderr': ''}]},
    'gate': {'verdict': 'reject'},
})
ep['gates']['prediction_delta'] = {
    'matched': False, 'unmet_expectations': ['pytest'], 'unexpected_failures': [], 'invariants_recorded': True,
}
print(render_episode_block(ep, ep_id='ep_demo_01'))
"
```

你看，提示词里只花了不到十行字，就给出了两条硬信息：
1. `- prediction_delta: matched=False unmet=["pytest"] unexpected=[]` —— 你押错了。
2. `- check \`pytest -q\` stdout truncated at 400/530 chars; call \`episode_inspect\` to zoom in` —— 后面还有 130 个字符被截掉了，别瞎猜，调 `episode_inspect` 把截断后的内容读回来，一眼就能抓出 `FAIL test_edge_case: AssertionError: 1.5s != 1.0s`。

不盲猜、不失忆、不拿口头汇报当证据。那么最后一个问题来了：**就算每一轮都这么老老实实记下来了，你怎么证明攒下来的这些 Episode 经验，真的让智能体比以前更会解题了？**

👉 **[下一讲：怎么证明它真的变强了？（冻结包、密封题与消融盲测）](./05-measuring-real-progress.md)**
