# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)

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

## インストール

### 前提条件

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- Anthropic API キー（または互換プロバイダ）

### 開発環境のセットアップ

```bash
git clone https://github.com/EvoMap/evolver.py.git
cd evolver.py
uv sync
```

### 環境変数

```bash
# .env ファイル（リポジトリルート）
ANTHROPIC_API_KEY=sk-ant-...
A2A_HUB_URL=https://evomap.ai          # Hub エンドポイント
EVOLVER_NO_PARENT_GIT=1                # 親 .git を無効にする
OPENCLAW_WORKSPACE=/path/to/project    # ワークスペースルート
```

## コマンドリファレンス

| コマンド | 説明 |
|----------|------|
| `uv run evolver` | 1 回の進化サイクル |
| `uv run evolver --loop` | デーモンループ |
| `uv run evolver --review` | レビューモード |
| `uv run evolver --solo` | 完全オフラインモード |
| `uv run evolver solidify` | 保留中の変異を適用 |
| `uv run evolver start / stop / restart / status` | デーモンライフサイクル |
| `uv run evolver log` | デーモンログの表示 |
| `uv run evolver check / watch` | ヘルスモニタリング |
| `uv run evolver webui` | WebUI ダッシュボード |
| `uv run evolver proxy` | A2A プロキシの起動 |
| `uv run evolver proxy-token` | プロキシトークンの発行 |
| `uv run evolver setup-hooks --platform cursor` | IDE フックのインストール |
| `uv run evolver self-report` | Autopoiesis 自己診断 |
| `uv run evolver distill` | LLM 応答の蒸留 |
| `uv run evolver fetch <query>` | Hub からの資産取得 |
| `uv run evolver publish <id>` | Hub への公開 |
| `uv run evolver sync` | Hub との同期 |
| `uv run evolver asset-log` | 資産呼出ログ |
| `uv run evolver recipe list / show / apply` | レシピ管理 |
| `uv run evolver skill2recipe` | スキルからレシピへの変換 |
| `uv run evolver atp balance / buy / orders / verify` | ATP マーケットプレース |

## 例

| 例 | 説明 |
|---|---|
| [`examples/hello-world/`](examples/hello-world/) | 1 回の進化サイクル |
| [`examples/daemon-loop/`](examples/daemon-loop/) | デーモンループとライフサイクル管理 |
| [`examples/proxy-basics/`](examples/proxy-basics/) | プロキシ設定と curl API 例 |
| [`examples/ide-hooks/`](examples/ide-hooks/) | 5 プラットフォーム用 IDE フック |
| [`examples/solo-mode/`](examples/solo-mode/) | 完全オフライン隔離モード |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis 自己診断レポート |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | 蒸留→再利用→公開のライフサイクル |
| [`examples/skill2recipe/`](examples/skill2recipe/) | スキル→レシピ合成 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP マーケットプレースデモ |

## プロジェクト構造

```
evolver.py/
├── src/evolver/
│   ├── cli.py              # CLI エントリポイント
│   ├── config.py           # ランタイム設定
│   ├── gep/                # GEP コア（遺伝子、カプセル、プロトコル）
│   ├── evolve/             # 進化パイプライン
│   ├── proxy/              # A2A プロキシ
│   ├── webui/              # WebUI ダッシュボード
│   ├── ops/                # 運用ツール（ヘルス、修復、トリガー）
│   ├── atp/                # エージェント取引プロトコル
│   └── adapters/           # IDE フックアダプター
├── tests/
├── examples/               # 実践ガイド（全機能をカバー）
└── docs/                   # 設計書とロードマップ
```

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
- [README.ko-KR.md](README.ko-KR.md) — 한국어
- [SKILL.md](SKILL.md) — AI エージェント用スキル定義
- [CONTRIBUTING.md](CONTRIBUTING.md) — コントリビューションガイド
- [AGENTS.md](AGENTS.md) — AI エージェント向け参照
- [设计方案.md](设计方案.md) — 設計書（中文）
- [TODO.md](TODO.md) — ギャップ分析とロードマップ
- [演进方案.md](演进方案.md) — v1.89.11 対追跡計画（中文）

## ライセンス

Apache-2.0 — 詳細は [LICENSE](LICENSE) を参照してください。
