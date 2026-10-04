# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · [简体中文](README.zh.md) · **日本語** · [한국어](README.ko-KR.md)

**GEP 駆動の AI エージェント自己進化エンジン。**

エンジンは LLM を呼ばない。MCP stdio で接続したホスト Agent が実行器になる。現行段階はそのループを凍結済み外部タスクパックへ向ける。章程は [演进方案.md](演进方案.md)（中国語）。本ツリーは `@evomap/evolver` の行動等価 Python ポートで、次の技術基盤を使う：

- **Python 3.12+** — `asyncio`、型パラメータ構文（`list[str]`）、`tomllib`
- **uv** — 高速 Python パッケージ管理
- **Pydantic v2** — スキーマ検証と設定
- **httpx** — 非同期 HTTP クライアント（Node の `undici` 相当）
- **FastAPI + uvicorn** — ローカル Proxy と WebUI（任意の `server` extra）

> **注**: GEP コア、進化パイプライン、Proxy ルート、認知編成は概ね実装済み。ATP 商業ループと Validator サンドボックスは部分的で、現行段階の対象外。

---

## クイックスタート

```bash
# 依存関係のインストール（プロジェクトローカル環境）
uv sync

# 1 回の進化サイクル
uv run evolver

# デーモンループ
uv run evolver --loop

# レビューモード
uv run evolver --review

# WebUI ダッシュボード（server extra が必要）
uv run evolver webui

# ローカル A2A プロキシ
uv run evolver proxy
```

> WebUI とローカル Proxy には server extra が必要：`uv sync --extra server`。コア進化エンジンと MCP サーバーに fastapi 依存は無い。

**ホスト Agent を群に参加させる（v1.98+ の旗艦機能）** — エンジンが MCP stdio 経由でホストを乗っ取り、GEP 変異プロンプトの実行器にする。1 コマンドでフルループを体験：

```bash
uv run python examples/swarm-quickstart/demo_swarm_loop.py            # 決定的デモ（LLM 不要）
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py     # クローズドループ全体
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm   # DeepSeek が実際に実行
```

詳細は [MCP 群進化](#mcp-群進化) と [examples/swarm-quickstart/](examples/swarm-quickstart/)。

### uvx（ワンショット / プロジェクトインストールなし）

evolver 公開後（または `uv sync` せずツール分離したい場合）：

```bash
# PyPI から（公開後）
uvx evolver --help
uvx evolver run

# ローカルチェックアウトから（グローバルインストール不要）
uvx --from . evolver run
uvx --from . evolver --loop
```

### ランチャー選択

デーモン再起動、ライフサイクル `start`、IDE hooks は `EVOLVER_LAUNCHER` で再呼び出し方法を決める：

| 値 | 動作 |
|---|---|
| `auto`（既定） | `uv` + プロジェクトルートがあれば `uv run evolver`、なければ `uvx`、それもなければ `python -m evolver` |
| `uv` | `uv run [--project <root>] evolver …` を強制 |
| `uvx` | `uvx [--from <root>] evolver …` を強制（`uvx` シムがなければ `uv tool run`） |
| `python` | `python -m evolver …` を強制 |

監督者は `EVOLVER_LOOP_COMMAND`（空白区切り）で argv 全体を上書きできる。

## MCP 群進化

stdio MCP サーバーを通じて evolver は **ホスト Agent を GEP 変異プロンプトの実行器**にする。エンジン自身は LLM API を呼ばず、接続されたホスト（ZCode / Claude Code / Cursor / …）こそが実行器（v1.98.0+）。

### ホスト接続設定

起動コマンドは `uv run evolver mcp`（プロジェクト内）または `<venv>/bin/python -m evolver.mcp_server`（絶対パス — ホスト設定にはこちらを推奨）。

**ZCode**（ワークスペース/ユーザー `settings` の `mcpServers`）：

```json
{
  "mcpServers": {
    "evolver": {
      "command": "/absolute/path/to/evolver.py/.venv/bin/python",
      "args": ["-m", "evolver.mcp_server"],
      "env": {
        "EVOLVER_SWARM_AUTO_HIJACK": "0"
      }
    }
  }
}
```

**Claude Code**（プロジェクトルート `.mcp.json`）と **Cursor**（`.cursor/mcp.json`）も同形。完成済み設定は [`examples/swarm-quickstart/mcp-host-configs/`](examples/swarm-quickstart/mcp-host-configs/)。

> よく使う環境変数：`EVOLVER_SWARM_AUTO_HIJACK=1`（HITL を強制的に開き、ホスト中継の承認を拒否。常駐 instructions は変わらない）；`EVOLVER_HITL_MODE=on`（高リスク solidify に人間承認が必要）；`EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`（連続劣化フィードバック N 回で自動一時停止、既定 3）。

### 乗っ取りとクローズドループ

- **注入**: このメッセージに別のタスクが既にあればそれを実行。なければ `swarm_boot` を呼び、実際の状態を一言で述べる。`boot_once` はセッション登録のみで、起動時にスキル同期はしない。凍結パックまたは Parent ベースラインが無い場合、ループ一時停止中は tick しない（人間は `EVOLVER_SWARM_GATE_HANDOFF=hotl` で前者 2 項目を飛ばせる。ゲートは発行を拒否し続ける）。「止めて」「続けて」と言われたらホストが `swarm_supervise` の pause / resume を中継する。初回準備（凍結パック、別コンテキストでの val 開封、ベースライン作成）は [examples/swarm-quickstart/README.md](examples/swarm-quickstart/README.md)。全文プロトコルは MCP プロンプト `evolver_swarm` と `swarm_boot` の返答にある
- **クローズドループ手順**: `swarm_tick`（GEP 変異プロンプト取得）→ ホストが自身の編集ツールで変異を実行 → `swarm_distill`（Gene/Capsule 蒸留）→ `swarm_hypothesis`（一仮説ゲート：ホストが当該ラウンドの唯一の仮説を宣言。無ければ拒否）→ `swarm_solidify`（検証ゲート + 固化）→ `swarm_feedback`（統一評価シグナル E、低スコアは repair-bias 自動注入）→ ループ。`swarm_propose` でエビデンスパックから介入提案、`swarm_report` はハートビート
- **二重安全ゲート**: HITL 承認ゲート（`evolver hitl list|approve|reject`、TTL 失効は fail-safe で REJECT）+ HOTL 監督（`evolver supervise status|pause|resume|direct|veto|unveto` — 人間はいつでもブレーキ・拒否・転換できる）

### Hooks 連携（シグナル自動収集）

ホストがファイル hooks をサポートする場合はインストールする。セッション境界とツール出力中のエラーシグナルが自動的に進化記憶へ流れる：

```bash
uv run evolver setup-hooks --platform auto --project-dir /path/to/workspace
# プラットフォーム: cursor | claude-code | codex | kiro | opencode | vscode | generic | auto
```

MCP ホストのみ（ファイル hooks 能力なし）は**プロセス内ブリッジ**を使う：セッション開始/終了時やエラー出力観測時に `swarm_hook_event` を呼ぶ（`event=session_start|session_end|signal_detect`、`payload.content` に本文）。検出シグナル（`log_error` / `perf_bottleneck` / …）は次サイクルの遺伝子選択に直結注入される。`swarm_hooks`（`action=status|install|uninstall`）でホスト自身がファイル hooks を導入することもできる。

### MCP リソースとツール注釈

ツールに加えて 4 つの読み取り専用リソースを公開（ホストは購読またはツール往復なしで読める）：

| URI | 内容 |
|---|---|
| `evolver://status` | ライブエンジン/群状態（JSON、HITL/HOTL/フィードバック要約を含む） |
| `evolver://instrument-prompt` | 現在レンダリングされた乗っ取りプロンプト |
| `evolver://dispatch/last` | 直近の GEP 変異プロンプト（`last_prompt.md`） |
| `evolver://events/recent` | 直近の進化サイクルタイムライン（JSON） |

ツール面は 26 個：汎用 8 個（`asset_search`、`asset_get`、`episode_get`、`mailbox_send`、`mailbox_poll`、`mailbox_ack`、`rebuild_views`、`cycle_timeline`）+ 群 18 個（`swarm_boot` / `tick` / `distill` / `hypothesis` / `propose` / `solidify` / `feedback` / `report` / `status` / `approvals` / `approval_resolve` / `supervise` / `hooks` / `hook_event` / `skills` / `workflow_run` / `workflow_act` / `workflow_status`）。

ツールには MCP 仕様注釈が付く：`swarm_status`、`swarm_approvals`、`asset_search`、`episode_get`、`cycle_timeline` などは `readOnlyHint`（プランモードで確認スキップ可）；`swarm_solidify`、`swarm_hypothesis`、`swarm_propose`、`swarm_supervise`、`swarm_approval_resolve`、`swarm_workflow_act` は `destructiveHint`（ホストはユーザー確認を求められる）。

### スキル生態ブリッジ（SKILL.md → スキル遺伝子）

ホスト生態のスキルファイルを進化エンジンへ橋渡し（EvoX SkillRegistry パターン：**project > user > builtin の優先、同名遮蔽**）。探索ルート：ワークスペース `.agents/skills` と `.claude/skills` > ユーザー `~/.agents/skills`、`~/.zcode/skills`、`~/.claude/skills` > エンジン組み込み（`EVOLVER_SKILL_ROOTS` で上書き、順序＝優先度）。

```bash
uv run evolver skills scan              # 発見のプレビュー（優先度と遮蔽込み）
uv run evolver skills sync --dry-run    # 導入予定スキル遺伝子のプレビュー
uv run evolver skills sync              # GEP アセットストアへ変換（gene_distilled_s2g-*）
uv run evolver skills list              # ストア内のスキル遺伝子一覧
```

同期後、スキルは遺伝子としてシグナル照合と選択に参加する——「ImportError 修正」スキルはシグナル命中時に GEP プロンプトへ選ばれる。ホストは MCP `swarm_skills`（`scan|list|sync`）でも自助操作できる。

### 進化ワークフロー（EvoX 収穫：コラボレーションをデータに）

コラボレーション一式を **YAML ワークフロー**として表現（diff 可能 → 進化可能）：`agent` ステップは `role`/`instruction` を宣言してホスト実行器が担当、`gate` ステップは検証カスケード（ruff→mypy→pytest）をエンジン側で実行、`approval` ステップは人間承認ゲート。全体が WAL 永続・再開可能（Sprint 24.10 エンジン + v1.110.0 拡張）。

```bash
uv run evolver workflow templates                  # 同梱テンプレート: repair / innovate
uv run evolver workflow run --template repair      # 修復ループ起動（YAML ファイルも可）
uv run evolver workflow awaiting <id>              # ホスト実行器 / 承認者の現在の担当
uv run evolver workflow complete <id> --result '{"ok": true, "files": 2}'
uv run evolver workflow approve <id>               # 承認して解放
```

MCP 側：`swarm_workflow_run`（ファイルまたはテンプレートで開始）、`swarm_workflow_act`（approve/reject/complete/resume/cancel）、`swarm_workflow_status`（全状態 + ホストの担当）。

### 制御実験と消融判定

消融ベンチマークは、過去のエピソード記録がホスト自己修復を実際に改善するかを検証する（SelfSearch プロトコル、arXiv:2609.37968v2）。自己申告のスコア向上ではなく、厳密なオフライン/オンライン制御評価ハーネスを提供：

```bash
# 過去記録あり/なしでのタスク性能対照（実 LLM ブラインドテスト）
uv run evolver experiment --ablation --tasks tasks.json \
    --from-episodes --placebo --model deepseek-flash --output result.json
```

主要な科学的防御策：
- **プラセボ対照（`--placebo`）**: 記録なしアームに同長の中性ブロックを与え、プロンプト存在バイアスを排除。差分は記録の*内容*のみを評価する。
- **段階出口契約（`--stage-exit`）**: 出口を機械強制——実エピソード + プラセボ + 一意タスク + 確定コミット + レポート保存、欠けたら exit 2 でレポートなし。シード付き AB/BA 交互配置、呼び出しごとの記録（レイテンシ、トークン 3 分割、エラー分類、served model）、タスクごとの対応付き正確検定、サンプリング固定、サーバーサイド・プロンプト不均衡計測をレポートに同梱。
- **標本充足性監査**: `MIN_N=30` と照合。力不足の標本は結論に自動で `indicative only` を明記。
- **帰属の透明性**: 成功率の実向上（`success_rate`）とトークン同数のタイブレーク（`tokens_only`）を厳密に区別。
- **呼び出しグラフ境界ガード**: エピソード記録器はユニットテストで全 `src/` を走査し（`test_the_record_writer_is_confined_to_a_declared_boundary`）、変異やベンチランナーが自分自身を記録・採点できないことを保証。

## 前提条件

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — 必須。ロールバック・爆発半径計算・solidify に git を使う。git 以外のディレクトリでは明確なエラーで失敗する。
- **[uv](https://docs.astral.sh/uv/)** — 推奨。`uv sync`、`uv run`、`uvx` が使える。標準の `pip` / `python -m` も可。

## CLI コマンドリファレンス

| コマンド | 説明 |
|---|---|
| `run` | 1 回の進化サイクル（既定） |
| `--loop` / `--solo` / `--review` | デーモンループ / 完全オフライン（`--loop` を含意） / 人間レビューで停止 |
| `start` `stop` `restart` `status` `log` | デーモンライフサイクル |
| `check` `watch` | ヘルスチェックとヘルス監視 |
| `solidify` | 保留中の変異（または提案）を適用 |
| `apply-proposal` | 遺伝子提案 JSON を機械適用（アンカー検証済み・ワークスペース安全） |
| `review` | 保留 solidify のレビュー |
| `report` | サイクル判定レポート（負の結果もそのまま）+ パターン投影 |
| `gate-report` | 受容ゲート soak レポート：shadow 指標 + 昇格判定 |
| `variants` | 拒否されたが保存された候補のバリアント保管（RSI P1-3） |
| `charter-check` | 機械レシート：章程遵守とドリフトの検証 |
| `anchor init\|list\|run` | ツリー外アンカースイート：凍結検証契約（RSI P0-1） |
| `meta-report` | 改善機構テレメトリ：RSI Table-8 パネル + 子孫品質 |
| `gene-lifecycle list\|evaluate\|reinstate` | 遺伝子ライフサイクル統治（active / under_review / retired） |
| `soak setup\|exports\|status` | 進化ランタイム状態を git ツリー外に保持 |
| `session start\|resume\|status\|round\|hypothesize\|reject\|accept\|incomplete\|extend\|finalize` | ペア進化セッション（ラウンド予算は開始時に 8 で凍結；`extend` は人間のみ） |
| `self-report` | Autopoiesis 自己診断とルール進化 |
| `bench list\|init\|freeze\|gate\|baseline\|run\|prompt\|grade\|compare` | タスクパック、Parent ベースライン、`--library` 付き求解プロンプト、対応比較 |
| `library establish-parent` | Parent ライブラリスナップショットの初回書き込み（solidify からは到達不能） |
| `episode list\|show` | エピソード記録——1 回の自己改善ラウンドのランタイム記録 |
| `exec` `distill` `fetch` `reuse` `publish` `sync` `asset-log` `replay` `rebuild-views` | 実行ブリッジ、LLM 出力蒸留、Hub 取得/再利用/公開、資産呼出ログ、SQLite リプレイ、派生ビュー |
| `skill2recipe` | 検証済みスキルを公開可能な GEP レシピへ合成 |
| `mcp` | MCP サーバーを stdio で実行（群の入口） |
| `hitl list\|approve\|reject` | HITL 承認ゲート |
| `supervise status\|pause\|resume\|direct\|veto\|unveto` | HOTL 監督 |
| `skills list\|scan\|sync` | スキル生態ブリッジ |
| `workflow run\|templates\|status\|awaiting\|approve\|reject\|complete\|resume` | 耐久ワークフローエンジン |
| `experiment --ablation …` | 制御実験 / 消融判定 |
| `webui` `login` `logout` `webui-token` `reset-local-secret` `setup-hooks` `trajectory` | ダッシュボード、OAuth、トークン、IDE hooks、トレース→軌跡エクスポート |
| `atp` `atp-complete` `buy` `orders` `verify` | ATP ローカル決済、auto-buyer 同意、発注 |
| `proxy` `proxy-token` | A2A プロキシとローカル bearer トークン |
| `recipe list\|show\|apply\|cache-list\|cache-clear` | レシピハブ |

各サブコマンドは `--help` で全フラグを表示。

## プロジェクト構造

```
src/evolver/
├── cli.py              # CLI エントリポイント（argparse）、.env 読込、分派
├── config.py           # ランタイム閾値 + 環境変数
├── canary.py           # フォーク・カナリー：CLI がクラッシュせず読めるか検証
├── swarm.py            # 群コア：乗っ取りプロンプト + ループツール
│                       #   (tick/distill/hypothesis/propose/solidify/feedback/
│                       #    report/status/supervise/hooks/hook_event/skills)、
│                       #   stdout 全捕獲
├── mcp_server.py       # MCP stdio サーバー：汎用 8 + 群 18 ツール、
│                       #   evolver_swarm プロンプト、evolver://* リソース、
│                       #   ツール注釈（mcp>=2.0 MCPServer）
├── evolve/
│   ├── runner.py       # サイクル編成（単発 + デーモンループ）
│   ├── guards.py       # 離陸前チェック（負荷、RSS、クールダウン）
│   ├── post_cycle.py   # サイクル後フック（ATP auto-buyer）
│   └── pipeline/       # 7 段階パイプライン + preflight（async 関数）
│       ├── collect.py      # ログ走査 + living_memory
│       ├── signals.py      # シグナル + guard/preflight/learning
│       ├── hub.py          # Hub クエリ
│       ├── enrich.py       # 記憶助言 + 双方向メモリ同期
│       ├── autopoiesis.py  # SelfReport + 恒常性 + 生存可能性
│       ├── select.py       # Gene/Capsule 選択 + イノベーション記録
│       └── dispatch.py     # GEP プロンプト + solidify 状態保存
├── gep/                # GEP（ゲノム進化プロトコル）コア
│   ├── schemas/        # Pydantic モデル：Gene、Capsule、Task、Protocol
│   ├── asset_store.py  # JSON/JSONL 永続化（オーバーレイ意味論）
│   ├── cognition.py    # 認知編成（recall/explore/curriculum/reflection）
│   ├── solidify.py     # 遺伝子適用 → 検証 → 永続化 → 公開
│   ├── selector.py     # シグナル照合 + エピジェネティクス偏り
│   ├── signals.py      # シグナル収集と分類
│   ├── feedback.py     # 統一評価シグナル E（EvoX 収穫）
│   ├── hitl.py         # HITL 承認ゲート（失効は fail-safe で REJECT）
│   ├── supervision.py  # HOTL オーバーレイ（pause/veto/directive + トリップワイヤ）
│   ├── skill_assets.py # SKILL.md ブリッジ（project > user > builtin）
│   ├── episode_record.py   # エピソード記録：1 回の自己改善のランタイム記録
│   ├── evolution_session.py# ペアセッション機械（§5.1）+ 一仮説ゲート
│   ├── library.py      # コンテンツアドレス・ライブラリスナップショット
│   ├── bench/          # 凍結タスクパック、採点、凍結ゲート、対応検定
│   ├── validator/      # サンドボックス実行器、レポーター、ステーク初期化
│   └── ...             # 100+ モジュール
├── proxy/              # ローカル HTTP プロキシ（既定 127.0.0.1:8081、ルート /v1/a2a）
│   ├── server/routes.py    # FastAPI ルート行列（task/ATP/extensions）
│   ├── router/             # LLM ルーティング、機能、SSE ストリーミング
│   ├── extensions/         # DM、セッション、スキル更新、トレース制御
│   ├── mailbox/store.py    # ローカルメールボックス JSONL 保存
│   ├── sync/               # Hub 双方向同期エンジン
│   └── lifecycle/manager.py# プロキシライフサイクル + ハートビート
├── atp/                # Agent 取引プロトコル市場
│   ├── protocol.py         # 列挙と Pydantic モデル
│   ├── auto_buyer.py       # 能力ギャップ自動発見（オプトイン、予算制）
│   ├── auto_deliver.py     # タスク自動受諾・納品
│   └── settlement.py       # ローカル元帳
├── adapters/           # IDE 統合フック
│   ├── hook_adapter.py     # 共有アダプタロジック
│   ├── setup_hooks.py      # Cursor / Claude Code / Codex / Kiro / OpenCode 用フック
│   └── scripts/            # ランタイムスクリプト（session_start、signal_detect）
├── ops/                # 運用（ライフサイクル、ヘルス、自己修復、soak 環境）
│   ├── lifecycle.py        # クロスプラットフォーム・デーモン管理
│   ├── health_check.py     # ディスク/メモリ/プロセス検査
│   └── self_repair.py      # Git 緊急修復
├── bench/              # ワークスペースベンチマーク（健康タスク + fitness 元帳）
├── experiment/         # 制御実験、実 LLM 消融、プラセボアーム、指標
├── recipe/             # レシピハブ（list/show/apply + キャッシュ）
├── solo/               # 制約付きオフラインモード（ネット/ATP/Validator を遮断）
└── webui/              # FastAPI 読取専用ダッシュボード
    ├── app.py            # ダッシュボード + SSE `/events/stream`
    ├── dashboard.py      # 自己完結ダーク HTML ダッシュボード（ライブイベント）
    ├── client/           # インライン JS/CSS（SSE、bootstrap、i18n）
    └── observer/         # データ集約モジュール

tests/                  # テストファイル 342、テスト 4,227（pytest；MCP プロトコル
                        #   E2E と tests/e2e/ の実 LLM ループ E2E を含む）
scripts/                # CLI ヘルパースクリプト 23（「スクリプト」参照）
src/evolver/assets/gep/ # シード遺伝子ライブラリ
memory/                 # ランタイムデータ（graph JSONL、reviews JSONL）
```

## 環境変数

| 変数 | 既定値 | 用途 |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | ユーザーごとのランタイム状態ディレクトリ |
| `EVOLVER_REPO_ROOT` | 自動検出 | リポジトリルート上書き |
| `OPENCLAW_WORKSPACE` | （未設定） | ワークスペースルート上書き |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP アセットストア |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | 進化状態 |
| `EVOLVER_SESSION_SCOPE` | （未設定） | プロジェクト単位の状態分離セグメント |
| `EVOLVE_STRATEGY` | `balanced` | 進化戦略プリセット |
| `EVOLVE_BRIDGE` | auto | Git worktree 変異ブリッジ |
| `EVOLVER_ROLLBACK_MODE` | `stash` | ロールバック戦略: stash / hard / none |
| `EVOLVER_MAX_CYCLES_PER_PROCESS` | `0`（無制限） | デーモン 1 プロセスあたり最大サイクル数 |
| `EVOLVER_CYCLE_TIMEOUT_MS` | `2700000` | 1 サイクルのハードタイムアウト |
| `EVOLVER_VALIDATOR_ENABLED` | オプトイン（`1`/`true` で有効） | Validator デーモン |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI ポート |
| `EVOLVER_PROXY_PORT` | `8081` | ローカルプロキシポート（`EVOMAP_PROXY_PORT` 別名）；`evolver proxy --port` で上書き |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL |
| `A2A_NODE_ID` | 自動生成 | ノード識別 |
| `GITHUB_TOKEN` | — | GitHub API トークン |
| `EVOLVER_HITL_MODE` | `off` | HITL 承認ゲート——`on` で高リスク solidify は人間承認待ち（off も監査記録；未知値は fail-closed で on） |
| `EVOLVER_HITL_TTL_MS` | `1800000` | HITL 保留リクエスト TTL——失効は fail-safe で REJECT |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL トリップワイヤ——連続 N 回の劣化で自動一時停止（`0` で無効） |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | 群フィードバック劣化閾値——下回る（または `success=false`）と repair-bias 注入 |
| `EVOLVER_ADAPTIVE_MUTATION` | `true` | フィードバック駆動の変異カテゴリ重み適応 |
| `EVOLVER_ADAPTIVE_MUTATION_SHIFT` | `0.2` | 適応重みシフト幅（正規化前） |
| `EVOLVER_SWARM_AUTO_HIJACK` | `false` | `1` で HITL を強制し、ホスト中継の承認を拒否。常駐 instructions は不変 |
| `EVOLVER_SWARM_GATE_HANDOFF` | `human` | 凍結パック/ベースライン欠如時：`human` は boot/tick を `await_human` に；`hotl` は tick 継続（ゲートは拒否・ロールバックし、何も公開しない） |
| `EVOLVER_SKILL_ROOTS` | 3 階層ルート | スキルルート上書き（os.pathsep 区切り、順序＝優先度） |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | 昇格判定の最小 gated 標本数（false-kill 上限 0.1、遮断率帯 0.05–0.5 はコード定数） |
| `EVOLVER_ACCEPTANCE_SHADOW` | `true` | shadow モード：判定は測定のみ、執行しない。`0` への切替は人間の決定 |
| `EVOLVER_FITNESS_GATE_ENFORCE` | オフ | `no_improvement` 変異を報告のみでなくロールバック |
| `EVOLVER_GENE_INERT_BAN_STREAK` | `8` | 不活性遺伝子が連続 N ラウンド無結果で選択禁止 |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | 適用済み遺伝子クールダウン窓——直近の成功固化は選択スコア減点 |
| `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY` | `0.25` | クールダウン減点係数（禁止ではない——単独一致は選択可） |
| `EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB` | `100` | memory_graph.jsonl ローテーション閾値 |
| `EVOLVER_MEMORY_GRAPH_RETENTION_COUNT` | `7` | 保持するローテーション保管数（`0` で全削除） |
| `EVOLVER_MEMORY_GRAPH_AUTO_ROTATE` | `true` | `false`/`0`/`no` で自動ローテーション無効 |
| `EVOLVER_ROTATE_GZIP_MAX_MB` | `32` | これを超えると rename のみ（gzip しない — OOM 防止） |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | 濫用防止テレメトリ（`heartbeat`/`off`） |
| `EVOLVER_OUTCOME_REPORT` | `off` | 再利用結果を Hub へ報告して帰属を得る |
| `EVOLVER_REUSE_ATTRIBUTION` | `off` | 再利用帰属モード |
| `EVOLVER_EVAL_WORKTREE_STRICT` | オフ | 評価 worktree 失敗時：`1` でライブ cwd にフォールバックせず失敗 |
| `EVOLVER_AUTOPOIESIS` / `EVOLVER_AUTOPOIESIS_WRITE` | `1` / `1` | Autopoiesis フェーズ / ルールと生きた記憶を永続化（`0`=dry-run） |
| `EVOLVER_LEARNING_SIGNALS` | `1` | 環境学習シグナル注入 |
| `EVOLVER_LAUNCHER` | `auto` | 再起動ランチャー：`auto` / `uv` / `uvx` / `python` |
| `EVOLVER_LOOP_COMMAND` | （未設定） | デーモンループコマンドの argv 全体上書き |
| `EVOLVER_FF_*` | フラグごと | 機能フラグ（`EVOLVER_FF_ENABLE_RECALL_INJECT`、`_REFLECTION`、`_EXPLORE`、`_CURRICULUM`、`_SKILL_AUTO_UPDATE` など）——環境変数がディスクフラグより優先 |

## 実装ステータス

> **総評**（2026-10-04）：パッケージバージョン **1.113.0**。ペアセッションは 2026-09-27 に収束し、封印 val で Parent を上回った候補はなかった。現行章程は [演进方案.md](演进方案.md)：経験を証拠に。出口は記録あり/なしの消融で、n=3 の合成記録は indicative only。受容ゲートは shadow のまま。下表の百分率は 2026-09-05 のスナップショット。

| サブシステム | 状態 | 備考 |
|---|---|---|
| **GEP データ層** | ~90% | シード遺伝子 11×sha256; solidify 直接テスト + 学習ヘルパー |
| **GEP 認知** | ~80% | recall/reflection/distill; explore/curriculum フラグ制御 |
| **進化パイプライン** | ~90% | 7 フェーズ + Autopoiesis + ハードタイムアウト; 適用済み遺伝子クールダウン（v1.111） |
| **MCP 群進化** | ~97% | 接管ループ + E フィードバック + HITL/HOTL + Hooks/スキルブリッジ + ワークフローツール; dogfood は round-78 まで |
| **ワークフローエンジン** | ~90% | WAL 永続ステップ（script/foreach/if/agent/approval/gate）; YAML + ロール + テンプレート（v1.110） |
| **受容ゲート** | ~85% | shadow soak + gate-report 判定; 執行スイッチは人間の決定権 |
| **プロキシ基盤** | ~85% | マルチプロバイダ、トークン再利用、パス CLI フラグ、ポート **8081** |
| **ATP 市場** | ~65% | ローカル決済; Hub 商用 E2E は保留 |
| **IDE アダプタ** | ~85% | ランタイムフック + py_compile ガード + MCP インプロセスブリッジ |
| **Ops / Solo** | ~85% | ライフサイクル、force-update、`--solo` |
| **WebUI** | ~70% | SSR ダッシュボード + GitHub observer |
| **Validator** | ~50% | サンドボックス基盤; 本番ネットワーク分離は保留 |
| **ドキュメント / リリース** | ~90% | CHANGELOG + バージョン **1.113.0**; マルチ OS CI（Windows は blocking + アンカースイート） |

進行中の計画は [演进方案.md](演进方案.md) と [TODO.md](TODO.md)。wikiskill 監査は史料。

## 例

| 例 | 説明 |
|---|---|
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **群進化フルループ** — MCP 接管、tick→実行→distill→solidify→feedback、HITL/HOTL 運用（`--llm` で DeepSeek が実行器；`demo_closed_loop_flash.py` で全体を実行） |
| [`examples/hello-world/`](examples/hello-world/) | 隔離ワークスペースで 1 回の進化サイクル |
| [`examples/daemon-loop/`](examples/daemon-loop/) | 常駐デーモン、ライフサイクル管理、start/stop/status/log |
| [`examples/proxy-basics/`](examples/proxy-basics/) | A2A プロキシ、proxy-token、curl API 例、LLM 中継 |
| [`examples/ide-hooks/`](examples/ide-hooks/) | Cursor / Claude Code / OpenCode / Codex のセッションフック |
| [`examples/solo-mode/`](examples/solo-mode/) | 完全オフライン隔離モード |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis 自己診断、教訓、自生ルール |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | 蒸留 → 再利用 → 公開の資産ライフサイクル |
| [`examples/skill2recipe/`](examples/skill2recipe/) | Agent スキルを GEP レシピへ合成 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP 発注/納品/ハートビートデモ（Hub モック可） |

## テスト

```bash
# 全テスト
uv run pytest tests/ -q

# 群フル E2E（stdio MCP、全ツール/リソース/プロンプト + HITL/HOTL）
uv run pytest tests/e2e/ -q

# 実 LLM ループ E2E — DeepSeek（deepseek-v4-flash）がホスト実行器役：
# tick → LLM が GEP dispatch プロンプトを実行 → distill → feedback → 2 回目の tick。
# 環境変数 DEEPSEEK_API_KEY が必要（無ければスキップ）。
DEEPSEEK_API_KEY=sk-... uv run pytest tests/e2e/ -m llm -q
# 任意: DEEPSEEK_BASE_URL（既定 https://api.deepseek.com）、
#       DEEPSEEK_MODEL（既定 deepseek-v4-flash）

# カバレッジ付き
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# 低速テスト除外（CI 既定）
uv run pytest -m "not slow"

# リント + フォーマット検査 + 型検査
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src

# 全モジュール import 検証
python scripts/validate_modules.py
```

## スクリプト

| スクリプト | 用途 |
|---|---|
| `scripts/a2a_export.py` | アセットを A2A JSON にエクスポート |
| `scripts/a2a_ingest.py` | A2A アセットをインポート |
| `scripts/a2a_promote.py` | 候補遺伝子を正式ストアへ昇格 |
| `scripts/analyze_by_skill.py` | スキル別進化イベント分析 |
| `scripts/baseline_snapshot.py` | 比較用ベースラインのスナップショット |
| `scripts/build_binaries.py` | PyInstaller スタンドアロンビルド補助 |
| `scripts/check_changelog.py` | CHANGELOG とバージョン整合検査 |
| `scripts/env_inventory.py` | 環境インベントリレポート |
| `scripts/extract_log.py` | events.jsonl を時刻/種別で抽出 |
| `scripts/generate_history.py` | GEP イベント年表（Markdown） |
| `scripts/gep_append_event.py` | GEP イベント手動追記 |
| `scripts/gep_personality_report.py` | パーソナリティ HTML レポート |
| `scripts/harness_governance_check.py` | ハーネス統治監査 |
| `scripts/human_report.py` | Markdown 進化レポート生成 |
| `scripts/recall_verify_report.py` | recall/メモリグラフ網羅率 |
| `scripts/recover_loop.py` | デーモンループ回復診断 |
| `scripts/seed_merchants.py` | ATP マーチャント定義シード |
| `scripts/self_ab_acceptance.py` | 自己 A/B 受容ヘルパー |
| `scripts/soak_env.py` / `scripts/soak_sprint24.py` | soak 環境ヘルパー |
| `scripts/suggest_version.py` | セマンティックバージョン上げ提案 |
| `scripts/validate_modules.py` | 全 import の検証 |
| `scripts/validate_suite.py` | import + 高速 pytest 統合ゲート |

## アーキテクチャ

### 進化パイプライン（7 段階）

**離陸前チェック**（`guards.py`）→ 任意で中断し SelfReport スナップショットを保存。

| 段階 | モジュール | 役割 |
|---|---|---|
| 1. Collect | `collect.py` | セッションログ、失敗診断、`living_memory` |
| 2. Signals | `signals.py` | シグナル抽出; guard / preflight / learning キー |
| 3. Hub | `hub.py` | Hub タスク/アセット; hub 品質ゲートデータ |
| 4. Enrich | `enrich.py` | メモリグラフ助言、`bidirectional_memory_sync` |
| 5. Autopoiesis | `autopoiesis.py` | SelfReport、生存可能性、恒常性、repair bias |
| 6. Select | `select.py` | Gene/Capsule + 変異カテゴリ |
| 7. Dispatch | `dispatch.py` | GEP プロンプト（`recall` + `autopoiesis_context`）、solidify 状態 |

**サイクル後**（`post_cycle.py`）— ATP auto-buyer tick。**solidify**（`evolver solidify`）は `gep/solidify.py` 経由で別途実行。

### 主要概念

- **Gene（遺伝子）** — 再利用可能な変異戦略（signals_match → execution_trace）
- **Capsule（カプセル）** — 結果付きの具体実行インスタンス
- **Epigenetics（エピジェネティクス）** — 環境感知の遺伝子抑制/活性化
- **Solidify（固化）** — 検証済み変異をコードベースへ適用
- **Episode record（エピソード記録）** — 1 回の自己改善ラウンドのランタイム記録。消融判定が拠る証拠源
- **ATP** — 自律サービス市場のための Agent 取引プロトコル

## Node.js リファレンスとの差異

- **ライセンス**: Python ポートは **Apache-2.0**（公開 API・テスト契約・仕様に基づくクリーンルーム行動等価再実装）。上流 Node.js リファレンスは GPL-3.0-or-later。
- **ソース可視性**: Python ポートは完全に読みやすく文書化済み。Node.js コアは難読化。
- **データベース**: Python ポートは `ops/sqlite_store.py` による SQLite 永続化を追加（拡張）。
- **レシピハブ**: Python ポートは `recipe/` モジュールを含む（新機能）。
- **WebUI フロントエンド**: Python ポートは SSE 付きインライン JS クライアント（`webui/client/`）。別ビルドの SPA ではない。
- **制御実験**: Python ポートは `experiment/` モジュールを内包し、プラセボ対照と標本量ゲート付きの厳密な消融判定を提供。

## セキュリティモデル

Evolver はファイルシステムとネットワークにアクセスする。ガードレールは多層で強制される：

- **離陸前ガード**: 陳腐化した `.git/index.lock` と保留中の rebase/merge を自動修復；負荷が `EVOLVE_LOAD_MAX` 超でサイクルスキップ；連続修復失敗で劣化モード（修復のみ）またはハード中断；ユーザーロック（`~/.evolver/user.lock`、TTL 付き）で IDE セッション中の変異を防止；`chore(release)` コミット近傍では進化をスキップ
- **爆発半径**: 各遺伝子は `constraints.max_files`（典型 4–20）と `forbidden_paths` を宣言；A2A ゲート `A2A_MAX_FILES=5`、`A2A_MAX_LINES=200`；`EVOLVER_ROLLBACK_MODE=stash` は適用前に stash し失敗時にロールバック
- **コンテンツ完全性**: アセット `asset_id` に `sha256:` ハッシュ、不一致エントリは読み込み時スキップ；`sanitize.py` が Hub アセットの危険フィールドを除去
- **ネットワーク安全**: Proxy は既定で `127.0.0.1` のみ待ち受け（`--host 0.0.0.0` は明示オプトイン）；Hub 通信はノード秘密鍵署名 + 濫用防止テレメトリ；`webui-token` は JWT を発行、WebSocket コマンドは admin ロール必要
- **ユーザー秘密**: `redact.py` がログから bearer トークン / API キー / JWT / パスワードを除去；`.env` と認証情報は決してコミットされない；セッション転記は WebUI 表示前に秘匿処理
- **群安全（HITL + HOTL）**: HITL は決定単位でブロック（高リスク solidify は `gep/hitl.py` を通過、TTL 失効は fail-safe で REJECT、subject 単位で冪等）；HOTL は監督オーバーレイ（pause/resume、veto、directive、連続劣化で自動一時停止）。すべての監督/承認操作は監査ログに記録

## 反例（うまくいかない使い方)

| しないこと | 理由 |
|---|---|
| git リポジトリなし（`/tmp` など）で evolver を実行 | 遺伝子は爆発半径追跡とロールバックに git に依存 |
| `OPENCLAW_WORKSPACE` を本番サーバーに向ける | Evolver はコード変異を適用する——隔離ワークスペースを使う |
| Hub 接続もシード遺伝子もなしに `--loop` | 遺伝子プールが枯渇。`EVOLVER_GENE_INERT_BAN_STREAK` を上げる |
| 同一ワークスペースで複数 evolver | インスタンスロックが防止。プロジェクト分離は `EVOLVER_SESSION_SCOPE` |
| `--solo` ですぐ結果を期待 | Solo には Hub アセットが無い。複数サイクルで育てる |
| CI/CD で `--review` を使用 | レビューモードは stdin で停止する。自動化は `--loop` |
| 同一リポジトリで Node.js と Python evolver を混在 | 状態ファイル形式が異なる。どちらかへ統一 |
| `EVOLVER_AUTOPOIESIS_WRITE=1` 設定直後に `LESSONS_LEARNED.md` を確認 | 教訓はサイクル完了後に非同期書き込み |
| 候補を書いた同じコンテキストで採点 | ペアセッションと bench の規則は val 求解を独立コンテキストで行うことを要求 |

## Hub 接続

Hub（`A2A_HUB_URL`、既定 `https://evomap.ai`）は資産発見（`GET /api/assets` または `evolver fetch`）、タスク市場（`evolver sync` またはプロキシエンドポイント）、ATP 決済、SSE + ポーリング双方向イベント同期を提供。接続は完全任意——`--solo` は Hub 機能を全て無効化。プロキシは接続ライフサイクルを管理（起動時 hello ハートビート、到達不能時の指数バックオフ 1s→30s、濫用防止テレメトリ、`A2A_NODE_SECRET_VERSION` による鍵ローテーション）：

```bash
A2A_HUB_URL=https://your-hub.example.com uv run evolver proxy
```

## ドキュメント

- [English README](README.md)
- [演进方案.md](演进方案.md) — 現行章程（中国語）
- [TODO.md](TODO.md) — その作業リスト
- [CHANGELOG.md](CHANGELOG.md) — ラウンドごとの記録（現在 1.113.0）
- [AGENTS.md](AGENTS.md) — エージェント統合ガイド、コーディング規約、落とし穴
- [DEBUG.md](DEBUG.md) — デバッグ手引き：dogfood とインターロックのバグ、根本原因と移行可能な教訓
- [RSI演进对照.md](RSI演进对照.md) — 論文対照と effective-L5 記録（史料、中国語）
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — 2026-09-01 監査（史料、中国語）
- [CONTRIBUTING.md](CONTRIBUTING.md) — コントリビューションガイド
- [SKILL.md](SKILL.md) — スキル使用リファレンス
- [docs/env-registry.md](docs/env-registry.md) — 環境変数レジストリ

## ライセンス

本プロジェクトは **[Apache License 2.0](LICENSE)** の下で配布されています。

> **上流系統に関する注記**: 本プロジェクトは、公開された API 仕様、テスト契約、プロトコル定義に基づいてゼロから独自にクリーンルーム実装された Python ポートです。オリジナルの Node.js リファレンス実装（`@evomap/evolver`）は EvoMap により GPL-3.0-or-later の下で配布されています。本リポジトリは Apache-2.0 で維持されています。
