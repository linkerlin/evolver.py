# 🧬 evolver.py

Python 3.12+ 之移植也，源于 [`@evomap/evolver`](https://github.com/EvoMap/evolver)，乃以 GEP 为驱动之 AI 智能体自进化引擎。

此移植之旨，在於与 Node.js 参考实现达成**完全行为等价**，同时采用现代 Python 工具链：

- **Python 3.12+**——`asyncio`、类型参数语法、`tomllib`
- **uv**——高速 Python 包管理
- **Pydantic v2**——模式验证与配置
- **httpx**——异步 HTTP 客户端（相当于 Node 之 `undici`）
- **FastAPI + uvicorn**——本地代理与 WebUI

## 快速上手篇

```bash
# 安装依赖
uv sync

# 运行单进化周期
uv run evolver

# 守护进程循环
uv run evolver --loop

# 审查模式
uv run evolver --review
```

## 项目结构篇

完整设计文档详见 `设计方案.md`（中文撰写，与源仓库文档语言一致）。

## 许可证篇

GPL-3.0-or-later（GNU 通用公共许可证第 3 版或其后续版本）
