# 第五讲：怎么证明它真的变强了？（冻结包、密封题与消融盲测）

二战期间，南太平洋有些岛民看到美军在岛上修了一条跑道、建了一座控制塔，戴着耳机对着话筒说话，天上就有装满食物和物资的飞机降落。
后来美军走了，岛民们渴望飞机再来。于是他们照着样子清出跑道，用竹子搭起控制塔，用两半椰子壳扣在耳朵上当耳机，还安排人举着两根竹棒在跑道上挥舞。形式一模一样，连细节都挑不出毛病。
但飞机再也没有降落过。

在 AI 智能体领域，这种“竹子控制塔”到处都是：
写了漂亮的反思提示词、建了复杂的记忆图谱、画了螺旋上升的架构图，然后跑了两道自己顺手编的测试题，看到通过了，就宣布：“我们的智能体实现了自我进化！”

这算科学吗？怎么可能算！
如果你想知道你的系统到底是“竹子控制塔”，还是真的能引来飞机，你必须过下面这三关。这也是 `evolver.py` 用来衡量自身演进的终极标尺。

---

## 第一关：尺子不能放在被测的人手里（冻结包与密封考卷）

如果你让一个学生自己给自己出考卷、自己批改，他肯定次次考 100 分。
同理，如果评测题放在代码仓库里面，而智能体又有权限改仓库里的文件，它迟早会学会“怎么把考卷改简单”或者“怎么把答案直接背进基因里”。

所以 `evolver.py` 的评测基准（`bench/` 与 `anchor/`）立下了三条死规矩：

1. **考卷冻结在仓库外面（`evolver bench freeze`）**：
   基准任务包被写进 `$EVOLVER_HOME/anchor/bench/`（比如 `~/.evomap/anchor/bench/charter-pack.tasks.json`），不在当前项目目录里，且绑定 SHA-256 摘要。每次给题目打分时，沙箱强制清理未声明的残留文件（防“幻影评分”），并且评分子进程自动剥离所有 `*_API_KEY` / `*_API_TOKEN` 等环境变量（`validation_env.py`）。
2. **起跑线只有一次首写机会（`evolver bench baseline`）**：
   进化还没开始前，Parent（父代基线）考了多少分，由 `establish_parent_baseline` 一锤定音写死。后面负责固化的 `solidify` 代码里根本调不到这个函数——谁也没法在没考好的时候偷偷把起跑线往后挪。
3. **考题一旦泄露，立刻打码作废（`val_seal.py`）**：
   任务包分训练题（`train`）和验证题（`val`）。验证题是密封的！
   什么意思？不管是在生成提示词、写入 `WORKING_SESSION.md` 草稿，还是调用 `episode_inspect` 切片的时候，引擎都会过一遍 `val_seal` 扫描器。如果发现某段经验记录里出现了 `val` 题目的专有特征串（哪怕是不小心带出来的），扫描器当场把它替换成 `[VAL_SEALED]` 打码掉。绝不允许把验证集考题背进提示词里作弊。

---

## 第二关：塞一段等长的废话进去比（`--placebo` 安慰剂对照）

现在我们来到核心问题：
在第四讲里，我们费尽心思把智能体每一次尝试修 bug 的过程（假设、diff、报错、预期落差）记成了 **Episode Record**，并在下一轮塞进提示词里当证据。
我们怎么知道塞进去的这段 Episode 记录**真的有用**？

有人说：“这还不简单！跑一遍带 Episode 记录的（处理组 Treatment），再跑一遍不带任何记录的（空白组 Control），看带记录的是不是得分更高！”

听起来很有道理，但这里藏着一个大坑：**大模型对提示词的长度和系统角色非常敏感。**
有时候你往系统提示词里多塞了 1500 个字，大模型因为看到上下文变长了、格式更严肃了，回答得就更仔细一点，分数就高了一点——哪怕你塞进去的只是一段抄菜谱的废话！

医学上测新药有用没用，绝不会给一组人吃药、另一组人什么都不吃；而是给另一组人吃一颗大小、颜色、味道一模一样的淀粉糖丸（安慰剂，Placebo）。

`evolver.py` 的消融实验（`evolver experiment --ablation --placebo`）干的就是这件事：
- **Treatment 臂（有记录组）**：注入真实的 `Episode Record`（比如 1200 个字符）。
- **Placebo 臂（安慰剂组）**：注入一段**字符长度完全相等、格式极其工整、但内容完全中性的占位文字**（刚好也是 1200 个字符）。

两边的模型、温度参数、题目顺序（用随机种子做 AB/BA 交错，消除先后出场偏置）完全锁定一致。如果 Treatment 赢不了等长的 Placebo，说明你攒的所谓“经验记录”跟一段等长的废话没有任何区别！

---

## 第三关：抛三次硬币全正面，不准开香槟（`MIN_N=30` 与 `--stage-exit`）

假设你做了上面的安慰剂对照实验，测了 5 道题：带记录的对了 4 道，安慰剂对了 2 道。
能宣布成功了吗？

**不能。** 因为只测 5 道题，随便抖一抖就会出现 4 比 2。
在 `evolver.py` 的实验统计模块（`experiment/stats.py` 与 `cli.py`）里，硬编码了样本量充足性门槛：**`MIN_N = 30`**。

- 当有效配对题目数 **`n < 30`** 时：不管带记录组赢了多少分，报告上的结论强制标为 **`indicative only`**（仅供参考），既不准凭它切大版本，也不准宣布阶段通过。
- 当 **`n >= 30`** 时：跑配对精确二项检验（`bench/compare.py`）。如果成功率没有显著提升，只是少花了一点 Token，只能标为 `tokens-only`；如果连这都没有，直接判 `no_signal`，诚实认输，停下来换思路。

为了防止人在跑实验的时候手软（比如挑自己喜欢的题目跑、或者跑出好结果才保存），命令里还有一个最严厉的机器契约开关——**`--stage-exit`**：
只要“真实 Episode 来源、开启 `--placebo`、题目无重复、工作区对应已知 Git commit、结果落盘到 `--output`”这五项里缺了任何一项，程序直接以 `exit code 2` 拒绝受理。

---

## 🔨 动手验证（1 分钟）

如果你手头有 `DEEPSEEK_API_KEY`，可以直接跑仓库里自带的真闭环脚本（它会真跑一轮变异生成 Episode，然后拿这轮 Episode 做一次微缩版的有/无记录对照）：

```bash
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_closed_loop_flash.py
```

要是手头没有 API Key 呢？一样能验证！我们直接调一次引擎的统计裁决器，看看当你在 5 道题上“大获全胜”（5 全对 vs 5 全错）时，引擎会不会被你忽悠过去：

```bash
uv run python -c "
from evolver.experiment.ablation import ablation_verdict

# 模拟只有 5 道题（n=5 < 30），哪怕有记录组 5 题全对、安慰剂组 0 题全错：
verdict = ablation_verdict({
    'control': 'placebo',
    'with_records': {'total': 5, 'succeeded': 5},
    'without_records': {'total': 5, 'succeeded': 0},
    'comparison': {'evolved_better': True, 'success_rate_delta': 1.0},
})
for k in ('verdict', 'sample_adequate', 'n_per_arm', 'conclusion'):
    print(f'{k}: {verdict[k]}')
"
```

看到打印出来的 `sample_adequate: False` 和 `conclusion: records changed the improvement behavior (indicative only: n=5 per arm < 30)` 了吗？哪怕是 5 比 0 的完美战绩，只要题量不够 30 道，裁判照样只给你盖一个 `indicative only` 的戳。

---

## 写在最后：把整台机器装回脑子里

现在，合上这五讲教程，你脑子里的 `evolver.py` 应该不再是一堆拗口的英文缩写，而是一幅很清楚的画面了：

1. 它平时翻日志找故障标签（**Signal**），去卡片盒里挑一张写好步骤和红线的菜谱（**Gene**）以及过往留样（**Capsule**），连同“以前怎么失败的”证据包一起印成派工单。
2. 它自己不养大模型，而是通过 **MCP** 把派工单发给你的 Cursor 或 Claude Code 去动刀；你在旁边握着 **HITL / HOTL** 刹车线。
3. 动手交卷前必须先押注（**`swarm_hypothesis` + `expected_outcome`**）；看不清截断报错就带着问题去调原件（**`episode_inspect`**）；上下文快满就先把草稿存进 **`WORKING_SESSION.md`**；最后由 **`solidify`** 核对文件数、跑测试、记下预期落差（**`prediction_delta`**），封存成不可篡改的 **`Episode Record`**。
4. 至于攒下来的这些经验到底有没有用？拉到仓外冻结考场上，跟等长的安慰剂（**`--placebo`**）做满 30 道题以上的配对盲测。真赢了才算数，没赢就老老实实承认没信号。

不背黑话，不玩竹子造的假机场，每一分进步都拿实验和账本说话。
事情就是这样。
