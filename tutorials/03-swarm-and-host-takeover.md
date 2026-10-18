# 第三讲：蜂群接管——为什么引擎自己不调大模型？

上一讲我们看到，`evolver.py` 跑完七步流水线，只吐出了一张“派工单”（GEP 提示词），然后就停下来等 `solidify` 验货了。

你肯定会问：为什么不在引擎里直接写几行 `openai.ChatCompletion.create()`，让它在后台自己调大模型、自己改文件、自己跑 `solidify`？

我们先想一个画面。
要让大模型在你的代码库里真的修好一个 bug，它光发一段聊天文本是没用的。它得有工具：得能用 ripgrep 搜代码、能分段读文件、能精准替换某几行、能在改错的时候看编辑器报错。

如果你在 `evolver.py` 里自己造一套这样的工具链，会发生两件事：
1. 你花大半年造出来的轮子，远不如你手头每天在用的 **Cursor**、**Claude Code**、**Codex** 或 **ZCode** 好用。
2. 你得配两套 API Key、付两份 Token 钱，而且后台黑盒改代码的时候，你在编辑器里完全看不见它在干嘛。

所以 `evolver.py` 选了一条反过来的路：**既然你手头的 IDE 智能体（宿主）已经有最锋利的手术刀，那就别自己造刀了。让引擎通过 MCP 协议接管你的宿主，借宿主的刀干活。**

这就是 **蜂群进化（MCP Swarm Evolution）** 的全部秘密。

---

## 借刀干活是怎么跑起来的？

当你把 `evolver mcp` 配进 Cursor 或 Claude Code 的 MCP 列表后，你的 IDE 和 `evolver.py` 之间就拉起了一条标准输入输出（stdio）电话线。

在这个组合里，分工非常明确：
- **`evolver.py` 是教练兼裁判**：负责攒经验、发派工单、收假说、跑门禁测试、记账。
- **你的 IDE 智能体是场上的运动员**：负责读派工单、用 IDE 自带的文件读写工具改代码、然后按规矩回来交卷。

一轮标准的交卷流程，就是按顺序打 6 个电话（MCP 工具调用）：

```
1. swarm_boot       ──▶ “教练我上线了，现在能开练吗？”
2. swarm_tick       ──▶ “给我发这一轮的派工单（dispatch_prompt）！”
   （宿主自己在编辑器里读文件、改代码）
3. swarm_distill    ──▶ “我改完了，把我的改动提炼成候选 Gene / Capsule 吧。”
4. swarm_hypothesis ──▶ “在跑测试之前，我先押注：我改了哪、为什么能成、预计哪些检查会过。”
5. swarm_solidify   ──▶ “请启动门禁验货！过了就 git commit，没过就回滚并告诉我哪错了。”
6. swarm_feedback   ──▶ “把这轮的得分和诊断写进反馈账本，帮下轮调整方向。”
```

注意一个关键细节：如果这一个信号族下面已经连续失败了好几次，`swarm_tick` 印出的派工单上会标一行醒目的 **`PROPOSAL REQUIRED`**（或者返回 `proposal_required=true`）。这时候宿主**不准直接改文件**，必须改调 `swarm_propose` 先交一份干预提案。为什么？因为同一条路已经撞墙三次了，再闷头硬改只是浪费时间。

---

## 人在哪里踩刹车？（HITL vs HOTL）

既然宿主能一轮接一轮地转，万一它发疯了怎么办？系统给你装了两个不同维度的刹车踏板：

### 1. HITL（Human-In-The-Loop，人在环内审批门）
**管的是“单次危险动作”。**
比如宿主调 `swarm_solidify` 时传了 `skip_validation=true`（想跳过测试直接入库）。当 `EVOLVER_HITL_MODE=on`（或开了 `EVOLVER_SWARM_AUTO_HIJACK=1`）时，引擎当场拦住，返回 `next_action=await_human_approval`。
宿主必须停下来，用 `swarm_approvals` 把待批单读给你听。只有你点头批准（跑 `uv run evolver hitl approve --id ...`），这一步才能放行；超时不批，自动按拒绝处理。

### 2. HOTL（Human-On-The-Loop，人在环上监督与自动保险丝）
**管的是“整个循环让不让转”。**
平时你不用盯着它。但你可以随时对宿主说一句：**“停。”**
宿主就会调用 `swarm_supervise(action="pause")`。一旦暂停，后面的 `swarm_tick` 全部拒绝发新派工单。你说 **“继续”**，它才恢复。
你还可以下达转向指令（`direct`：“这轮优先把测试修稳”），或者一票否决某张你不信任的基因卡片（`veto`：“不准用 `gene_xxx`”）。

要是你去喝咖啡不在电脑前呢？HOTL 有一根**自动保险丝（Tripwire）**：只要连续 3 次（`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK=3`）收到的反馈分数不及格，保险丝自动熔断，循环立刻进入暂停状态等你回来处理。

---

## 🔨 动手验证（1 分钟）

不需要打开任何 IDE，也不需要配任何 API Key。仓库里有一个现成的演示脚本，它会在后台拉起真正的 `evolver mcp` 服务端，然后模拟一个宿主按顺序打完上面那一套电话，最后还演示一次“暂停 → 拒绝派单 → 恢复”：

```bash
uv run python examples/swarm-quickstart/demo_swarm_loop.py
```

跑完之后，盯着终端输出看三件事：
1. 看 `swarm_skills` 那一步：脚本是怎么把 `examples/swarm-quickstart/skills/demo-fix-import/SKILL.md` 这份外部技能文档，自动扫描并蒸馏成一张内部基因卡片 `gene_distilled_s2g-demo-fix-import` 的。
2. 看 `swarm_tick` 那一步：它选中的是不是刚才那张新蒸馏出来的技能基因？
3. 看最后 `supervise pause` 之后再调 `swarm_tick`：引擎是不是立刻返回了 `paused` 拒绝发单？

亲眼看过一遍，你就明白什么叫“引擎当裁判、宿主当手脚、人握刹车线”了。

下一讲，我们进入整套系统里最精彩的部分：**怎么防止 AI（以及你自己）在进化过程中自己骗自己？**

👉 **[下一讲：别自己骗自己——假说门、预期落差与跨轮重注视](./04-not-fooling-yourself.md)**
