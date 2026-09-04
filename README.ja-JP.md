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
uv run evolver mcp          # MCP stdio サーバー（群進化ホスト接続点）
```

## 主な機能

- **GEP プロトコル** — 監査可能な進化資産（Gene / Capsule / Event）
- **7 段階進化パイプライン** — collect → signals → hub → enrich → autopoiesis → select → dispatch
- **MCP 群進化（v1.98+ の旗艦機能）** — ホスト Agent を stdio で接続し GEP 変異プロンプトの実行器として乗っ取る（`evolver mcp` + `evolver_swarm` プロンプト）。HITL 承認ゲート / HOTL 監督 / Hooks 双方向ブリッジ / スキルブリッジ / 統一評価フィードバック E（低スコアは自動 repair-bias 注入）/ 適応的変異バイアス / 検収ゲート soak レポート
- **進化ワークフロー（v1.110+、EvoX 収穫）** — コラボレーション全体を **YAML ワークフロー** として表現（diff 可能 → 進化可能資産）。`agent` ステップは role/instruction を宣言しホスト実行器が担当、`gate` ステップは検証カスケード（ruff→mypy→pytest）をエンジン側で実行、`approval` ステップは人間承認ゲート。WAL で永続化・再開可能。バンドルテンプレート：`repair` / `innovate`
- **マルチプロバイダプロキシ** — Anthropic / Bedrock / Gemini / Vertex / Ollama / OpenAI（9 ルート）
- **ATP マーケットプレース** — 15 の CLI サブコマンド（buy / sell / settle / dispute）
- **IDE 統合** — Cursor / Claude Code / Codex / Kiro / opencode のランタイムフック
- **Autopoiesis** — SelfReport + ホメオスタシス + 自己修復（Python オリジナル機能）

```bash
uv run evolver workflow templates               # repair / innovate テンプレート一覧
uv run evolver workflow run --template repair   # 修復ループ起動（YAML ファイルも可）
uv run evolver workflow awaiting <id>           # ホスト実行器 / 承認者の現在の担当
```

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
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **群進化フルループ** — MCP 接管、tick→実行→distill→solidify→feedback、HITL/HOTL 運用（`--llm` で DeepSeek が実行器） |
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
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — wikiskill 監査とギャップロードマップ（中文）
- [TODO.md](TODO.md) — ギャップ分析とロードマップ
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — v1.89.11 対追跡計画（中文）

## ライセンス

Apache-2.0 — 詳細は [LICENSE](LICENSE) を参照してください。

## 実装ステータス

> **2026-09-05**: パッケージバージョン **1.111.0**。MCP 群進化スタック（v1.98–v1.111：接管ループ、評価フィードバック E、HITL/HOTL、Hooks / スキルブリッジ、適応的変異、検収ゲート soak、YAML ワークフローエンジン）が完了し全緑（**3455 テスト合格**、mypy strict 0 エラー）。本リポジトリ自身で 5 ラウンドの dogfood を実走——検収ゲート gated_runs=4。残りの深さギャップは [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md)（中国語）参照。

| サブシステム | 状態 | 備考 |
|---|---|---|
| GEP データ層 | ~90% | シード遺伝子 11×sha256; solidify 直接テスト + 学習ヘルパー |
| GEP 認知 | ~80% | recall/reflection/distill; explore/curriculum フラグ制御 |
| 進化パイプライン | ~90% | 7 フェーズ + Autopoiesis + ハードタイムアウト; 適用済み遺伝子クールダウン（v1.111） |
| MCP 群進化 | ~97% | 接管ループ + E フィードバック + HITL/HOTL + Hooks/スキル/ワークフローツール; dogfood 5 ラウンド |
| ワークフローエンジン | ~90% | WAL 永続ステップ（script/foreach/if/agent/approval/gate）; YAML + ロール + テンプレート（v1.110） |
| 検収ゲート | ~85% | shadow soak + gate-report 判定; 強制執行スイッチは人間の決定権 |
| プロキシ基盤 | ~85% | マルチプロバイダ、トークン再利用、パス CLI フラグ、ポート **8081** |
| ATP マーケット | ~65% | ローカル決済; Hub 商用 E2E は保留 |
| IDE アダプタ | ~85% | ランタイムフック + py_compile 構文ガード + MCP インプロセスブリッジ |
| Ops / Solo | ~85% | ライフサイクル、force-update、--solo |
| WebUI | ~70% | SSR ダッシュボード + GitHub observer |
| Validator | ~50% | サンドボックス基盤; 本番ネットワーク分離は保留 |
| ドキュメント / リリース | ~90% | CHANGELOG + バージョン **1.111.0**; マルチ OS CI |

## 主要な環境変数

| 変数 | デフォルト | 用途 |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | ユーザー状態ディレクトリ |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP アセットストア |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | 進化状態 |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub エンドポイント |
| `EVOLVE_STRATEGY` | `balanced` | 進化戦略 |
| `EVOLVER_AUTOPOIESIS` | `1` | Autopoiesis フェーズ有効化 |
| `EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB` | `100` | memory_graph.jsonl ローテーション閾値 |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | 反濫用テレメトリモード |
| `EVOLVER_PROXY_PORT` | `8081` | プロキシポート |
| `EVOLVER_NO_PARENT_GIT` | （なし） | `.git` 走査を無効化 |
| `EVOLVER_ROLLBACK_MODE` | `stash` | ロールバック戦略 |
| `EVOLVER_HITL_MODE` | `off` | HITL 承認ゲート（`on` で高危険 solidify は人間承認待ち） |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL トリップワイヤー — N 回連続劣化で自動一時停止 |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | 群進化フィードバック劣化閾値（下回ると repair-bias 注入） |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | 適用済み遺伝子クールダウン窓（選択スコアペナルティ） |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | 検収ゲート昇格判定の最小サンプル数 |
