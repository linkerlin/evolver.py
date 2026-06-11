# Hello World — 单次进化周期

在隔离工作区运行一次 GEP 进化周期（不修改 Hub、不启动 Proxy）。

## 前置条件

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

## 步骤

```bash
# 仓库根目录
uv sync

# 使用临时工作区（推荐）
export OPENCLAW_WORKSPACE="$(pwd)/examples/hello-world/workspace"
export EVOLVER_NO_PARENT_GIT=1
mkdir -p "$OPENCLAW_WORKSPACE/memory"

uv run evolver
```

Windows PowerShell:

```powershell
$env:OPENCLAW_WORKSPACE = "$PWD\examples\hello-world\workspace"
$env:EVOLVER_NO_PARENT_GIT = "1"
New-Item -ItemType Directory -Force -Path "$env:OPENCLAW_WORKSPACE\memory"
uv run evolver
```

## 预期输出

终端应打印 `GENOME EVOLUTION PROTOCOL` 提示词片段，并在工作区生成：

- `memory/evolution/evolution_solidify_state.json` — 待固化状态
- `.evolver/gep/` — 本地 GEP 资产（若尚未存在则使用种子基因）

## 下一步

- 审查：`uv run evolver --review`
- 应用变异：`uv run evolver solidify`
- 仪表盘：`uv run evolver webui`
