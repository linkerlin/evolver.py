# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://opensource.org/licenses/GPL-3.0)

[`@evomap/evolver`](https://github.com/EvoMap/evolver) の **Python 3.12+ ポート** — GEP 駆動の AI エージェント自己進化エンジン。

Node.js 参照実装（v1.89.11）との**完全な動作等価性**を目標とし、現代的な Python ツールチェーンを使用します。

## クイックスタート

```bash
uv sync
uv run evolver              # 1 回の進化サイクル
uv run evolver --loop       # デーモンループ
uv run evolver --review     # レビューモード
uv run evolver webui        # WebUI ダッシュボード
uv run evolver proxy        # ローカル A2A プロキシ
```

## 主な機能

- **GEP プロトコル** — 監査可能な進化資産（Gene / Capsule / Event）
- **7 段階進化パイプライン** — collect → signals → hub → enrich → autopoiesis → select → dispatch
- **マルチプロバイダプロキシ** — Anthropic / Bedrock / Gemini / Vertex / Ollama / OpenAI（9 ルート）
- **ATP マーケットプレース** — 15 の CLI サブコマンド（buy / sell / settle / dispute）
- **IDE 統合** — Cursor / Claude Code / Codex / Kiro / opencode のランタイムフック
- **Autopoiesis** — SelfReport + ホメオスタシス + 自己修復（Python オリジナル機能）

## テスト

```bash
uv run pytest tests/ -q                    # 全テスト
uv run pytest -m "not slow" -q             # CI 用（低速テスト除外）
uv run ruff check src tests                # リント
uv run mypy src                            # 型チェック（strict）
```

## ドキュメント

- [README.md](README.md) — English
- [README.zh.md](README.zh.md) — 中文
- [设计方案.md](设计方案.md) — 設計書（中文）
- [TODO.md](TODO.md) — ギャップ分析とロードマップ
- [演进方案.md](演进方案.md) — v1.89.11 対追跡計画（中文）

## ライセンス

[GPL-3.0-or-later](LICENSE)
