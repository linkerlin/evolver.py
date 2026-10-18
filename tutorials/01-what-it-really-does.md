# 第一讲：扒掉术语外衣，这台机器到底在干嘛？

先忘掉“基因组进化协议（GEP）”和“自生系统（Autopoiesis）”这些词。

想象你带了一个很聪明的实习生写代码。
星期一，他在 Windows 上用 `Path("ruff").is_file()` 找工具，结果因为 Windows 可执行文件带 `.exe` 后缀，代码一直报错。你花了半小时教他：“在跨平台代码里找命令，别直接判断文件在不在，要用 `shutil.which`。”他听懂了，把 bug 修好了。

到了星期四，你开了一个新会话，让他写另一段找 `mypy` 的代码。你猜怎么着？他又写出了 `Path("mypy").is_file()`。

为什么？因为上一次对话关掉的时候，他的脑子就已经被格式化了。他只留下了那几行改好的代码，但**“为什么上次会错、遇到哪类报错该怎么修、改完要跑哪几条检查”**这套手艺，随着对话框关闭灰飞烟灭了。

`evolver.py` 要解决的，就这么一件事：**把修 bug 和做改动的“手艺”存进硬盘，下次遇到同类问题自动翻出来用，而且只留下真正管用的手艺。**

---

## 把四个核心名词翻译成人话

代码库里到处都是四个词：`Signal`、`Gene`、`Capsule`、`Solidify`。把名字拿掉，它们其实是厨房里的四样东西：

### 1. Signal（信号）＝ 烟雾报警器响了
引擎不会没事找事瞎改代码。它先去翻你的运行日志、上次失败的记录、测试报错。
比如它看到日志里反复出现 `ImportError` 或 `preflight_abort`，就会提取出一个标签，比如 `log_error` 或 `recurring_err:ImportError`。
**信号就是一句大白话：“这儿出事了，属于哪一类事。”**

### 2. Gene（基因）＝ 一张写着“遇到 X 就按 Y 步骤办”的菜谱卡片
既然报警器响了，怎么修？
普通做法是让大模型当场拍脑袋想一个办法。`evolver.py` 的做法是去 `.evolver/gep/genes.json`（和叠加层 `genes.jsonl`）里翻卡片。

一张卡片（`Gene`）长什么样？一点也不神秘，就是个 JSON 对象，里面写着四件事：
- **什么时候用我（`signals_match`）**：比如当信号里出现 `error`、`exception`、`failed` 时。
- **按哪几步做（`strategy`）**：第 1 步定位报错栈，第 2 步打最小补丁，第 3 步跑相关测试。
- **不准越过的红线（`constraints`）**：比如 `max_files: 12`（一次最多改 12 个文件），`forbidden_paths: [".git", "node_modules"]`（绝对不准碰这些目录）。
- **怎么验货（`validation`）**：比如 `["uv run pytest -q"]`。

看到没？所谓“基因”，就是**一张带了操作步骤、改动红线和验货命令的结构化 SOP 卡片**。

### 3. Capsule（胶囊）＝ 上次照着菜谱做成功的“留样照片”
光有菜谱还不够。如果上次有人照着这张菜谱修好过一个类似的坑，把当时的背景、改了哪几个文件、最后拿了多少分打包存起来，后来的人照着改就快得多。
这个打包好的成功案例，就叫 `Capsule`（存放在 `capsules.json` / `capsules.jsonl`）。如果改砸了呢？放进 `failed_capsules.json`，专门用来提醒后面的人：“这条死路有人走过了，别再踩。”

### 4. Solidify（固化）＝ 守在 `git commit` 门口的铁面保安
这是整套系统里最重要的一环。
大模型改完代码，最喜欢干的事就是拍胸脯说：“我已经圆满完成了修复！”
真的吗？不一定。可能它偷偷删了断言，可能它顺手改了 50 个无关文件，可能测试根本没跑通。

所以在 `evolver.py` 里，改完代码绝不能直接算完，必须过 `solidify` 这道门：
1. **查户口**：你动手之前声明本轮的唯一假说（Hypothesis）了吗？没写？退回！
2. **量尺寸**：你改的文件数超过 Gene 规定的 `max_files` 了吗？碰到 `forbidden_paths` 了吗？越界了？立刻 `git stash` / 回滚！
3. **跑验货**：按顺序跑 `ruff`、`mypy`、`pytest` 等验证命令。有一条挂了？回滚，把失败现场记进档案！
4. **盖章入库**：只有全部过关，才允许提交 Git、更新基因账本、把这次成功记成新的 Capsule。

---

## 为什么文件会有 `.json` 和 `.jsonl` 两份？

如果你打开 `.evolver/gep/` 目录，会发现既有 `genes.json`，又有 `genes.jsonl`。这又是干嘛？

想象你买了一本印刷好的菜谱书（`genes.json`）。你在做菜的时候改良了第三道菜的做法，你不会把整本书撕了重印，而是在书后面贴一张便签纸（往 `genes.jsonl` 末尾追加一行），写上：“同 ID 的那道菜，以我这张便签为准。”

这叫**叠加层（Overlay）**。读的时候，引擎先把 `.json` 读进来，再用 `.jsonl` 里同 ID 的新记录覆盖旧记录；写的时候，只往 `.jsonl` 末尾追加一行，既快又不容易写坏原文件。

而且每张卡片都有一个 `asset_id`，长这样：`sha256:8f3a...`。它是根据卡片内容算出来的哈希值。只要有人手动改了卡片里的一个标点符号却没重算哈希，引擎加载时一核对发现对不上，直接当损坏数据丢掉。这保证了进化的账本不会被偷偷篡改。

---

## 🔨 动手验证（1 分钟）

别光听我讲，直接去看看仓库里自带的“初始基因卡片”长什么样。在终端运行：

```bash
uv run python -c "
import json
from pathlib import Path
seed = json.loads(Path('src/evolver/assets/gep/genes.seed.json').read_text(encoding='utf-8'))
for g in seed['genes']:
    print('ID:', g['id'], '| 类别:', g['category'])
    print('  匹配信号:', g['signals_match'][:4])
    print('  最大文件数:', g['constraints']['max_files'], '| 禁区:', g['constraints']['forbidden_paths'][:3])
"
```

你会看到系统出厂自带的三张基础卡片：`gene_gep_repair_from_errors`（修错）、`gene_gep_optimize_prompt_and_assets`（优化）、`gene_gep_innovate_from_opportunity`（创新）。它们不是魔法，就是写清楚了触发条件、步骤和红线的 JSON 数据。

### 自检问题（看看你是不是真懂了）
如果不看上面的文字，你能回答这两个问题吗？
1. 如果你手动打开 `genes.json` 删掉了一个基因，为什么重启引擎后它又“复活”了？（提示：想想那本菜谱后面的便签纸 `genes.jsonl`。）
2. `Gene` 和 `Capsule` 的区别是什么？（一个是通用菜谱，一个是某次按菜谱做出来的具体菜肴留样。）

搞清楚这四个词，外衣就扒完了。下一讲，我们亲手摇动把手，看引擎怎么把这四样东西串成一圈。

👉 **[下一讲：亲手转一圈齿轮——从报警到入库的七步](./02-one-cycle-by-hand.md)**
