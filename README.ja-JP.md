# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · [简体中文](README.zh.md) · **日本語** · [한국어](README.ko-KR.md)

**GEP（Genome Evolution Protocol）駆動の AI エージェント自己進化エンジン。**

---

## 📖 概要：複利的な能力蓄積をもたらすエージェント進化へ

大規模言語モデル（LLM）を活用したソフトウェアエンジニアリングにおいて、従来のコーディングエージェントには大きな限界がありました。それは、**「単発推論による記憶の喪失」「成功戦略の定着機構の欠如」「厳密な進化基準の不足」**です。既存の AI ツールはコード差分を生成できても、過去の開発摩擦から自律的に学び、戦略を体系的に改善し続けることは困難でした。

**`evolver.py` は、この壁を突破するために設計されました。**

本プロジェクトは、**GEP（ゲノム進化プロトコル）** に基づく自己進化システムです。リポジトリや実行ログからエラーや摩擦信号（Signals）を検出し、最適な変異戦略（Gene）をマッチング・配信して外部ホストエージェントにコード改修を実行させます。厳密なサンドボックス検証と統計的対照アブレーション実験を経て、実証された知見を再利用可能な「遺伝子（Gene）」や「カプセル（Capsule）」として蓄積し、複利的な成長サイクルを確立します。

### 基本設計思想

1. **エンジンは推論を直接スケジューリングしない：ホストエージェントが実行器となる**  
   `evolver.py` は独自のプロプライエタリな LLM 呼び出し機構を持ちません。標準の **MCP (Model Context Protocol) stdio** 経由で、普段利用しているホストエージェント（Cursor、Claude Code、Codex、ZCode など）を進化の実行器として接続します。ホストの強力なツール環境やワークスペース文脈を変異のメスとし、エンジン側は意思決定・記憶管理・安全統制に専念します。

2. **経験こそが証拠・再帰的ハーネス工学（Experience as Evidence & Recursive Harness Engineering）**  
   最先端の自律研究プロトコル（*arXiv:2609.37968v2, SelfSearch*；*arXiv:2610.14224v1, Harness2*）に基づき、エージェントの実際の自己改善実行記録（Episode Record）を第一級の証拠として扱い、機械的な 4 方向コンポーネント帰属、ラウンド間行動対比差分、および複数提案の選択的合成を組み合わせます。ブラックボックスな当て推量や単純な自己採点を排し、事前整合性ゲート・厳格な対照アブレーション実験・統計的サンプルサイズ充足性監査によって進化を判定します（実 MCP 決済 30 件・凍結ペア課題 32 問の `--stage-exit` 出口検証にて 2 つの独立シードともに有意な `signal` を達成：`p = 1.86e-09` / `2.98e-08`）。

3. **クリーンルーム Python 実装**  
   公開仕様とテスト規約に基づき、`@evomap/evolver` の動作等価な Python 実装としてゼロから構築されています。最新の Python スタック（Python 3.12+、`asyncio`、`uv`、`Pydantic v2`、`httpx`、`FastAPI`）を採用し、寛容な **Apache-2.0** ライセンスで公開されています。

---

## 🏛️ システムアーキテクチャと進化ループ

`evolver.py` は、疎結合な非同期 7 段階パイプライン、GEP データモデル、そして多層防御安全機構によって堅牢に稼働します。

```
┌────────────────────────────────────────────────────────────────────────┐
│                      evolver.py 進化ライフサイクル                     │
└────────────────────────────────────────────────────────────────────────┘

  [ 実行時ログ / リポジトリ摩擦 / テスト失敗 ]
                         │
                         ▼
             ┌───────────────────────┐
             │   1. Collect (収集)   │ ── 障害追跡と生きた記憶 (Living Memory) を走査
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   2. Signals (信号)   │ ── エラーやボトルネックを構造化信号として分類
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   3. Hub Sync (同期)  │ ── 分散 Hub ネットワークから候補資産を検索
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   4. Enrich (強化)    │ ── 記憶グラフと失敗履歴を統合し文脈を拡充
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │ 5. Autopoiesis (自生) │ ── システム生命力を自己監査し防御規則を生成
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │   6. Select (選択)    │ ── 修復バイアスと新奇性を考慮し変異遺伝子を選択
             └───────────┬───────────┘
                         ▼
             ┌───────────────────────┐
             │  7. Dispatch (配信)   │ ── 証拠付き GEP 変異プロンプトを生成
             └───────────┬───────────┘
                         │
                         ▼  (MCP stdio 経由)
             ┌───────────────────────┐
             │ ホスト Agent (実行器) │ ── Cursor / Claude Code がコードを変異
             └───────────┬───────────┘
                         │
                         ▼
             ┌───────────────────────┐
             │ 仮説門と検証ゲート    │ ── 単一仮説を宣言しサンドボックス検証を実行
             └───────────┬───────────┘
                         │
                  [ 検証合格 ]
                         │
                         ▼
             ┌───────────────────────┐
             │ Solidify (固化・定着) │ ── Git コミット ➔ 遺伝子昇格 ➔ 適応フィードバック
             └───────────────────────┘
```

### 1. 7 段階進化パイプライン

各進化サイクルは 7 つの独立した非同期フェーズで構成されます：
- **Collect**：ローカル実行ログの分析、失敗診断の収集、`LESSONS_LEARNED.md`（生きた記憶）の読み込み。
- **Signals**：生データから構造化された信号（例: `log_error`、`perf_bottleneck`、依存関係の乖離）を抽出し、問題価値と WFQ 飢餓防止キューで優先順位付けを行い、アイドルスケジューラ強度（`signal_only` / `standard` / `deep`）に応じて探索枠を調整。
- **Hub**：中央または P2P ハブに問い合わせ、マッチする既存戦略やタスクを発見。
- **Enrich**：記憶グラフとの双方向同期、過去の介入結果や失敗要因の紐付け。
- **Autopoiesis（自己創出・自生）**：頻出する摩擦をガードルールとして自己符号化し、ホメオスタシス（恒常性）を維持。
- **Select**：修復バイアス（Repair Bias）と探索性を加味して最適な変異戦略を選択し、直前エピソードが `hurt` 帰属の場合は当該遺伝子を自動クールダウンして修復へピボット。
- **Dispatch**：詳細な証拠を含む GEP 変異プロンプトを構築し、ホストへ配信。

### 2. GEP 資産モデル

- **Gene（遺伝子）**：抽象的で再利用可能な変異戦略。「どのような信号パターン（`signals_match`）のときに、どのような改修（`execution_trace`）を行うか」を定義。
- **Capsule（カプセル）**：特定の入力、生成された差分、実行結果（成否）を保持する具体的な変異記録。
- **Epigenetics（エピジェネティクス調控）**：最近の環境フィードバックに基づき特定遺伝子を抑制・活性化し、局所的なループや振動を防止。
- **Gene Lifecycle（ライフサイクル管理）**：遺伝子を `active`、`under_review`、`retired` の 3 状態で厳格に管理。成果のない遺伝子は自動で降格・排除。

### 3. 多層安全防壁（HITL + HOTL）

コードを自己書き換えするシステムの安全性を担保するため、二重の安全防壁を実装しています：
- **HITL（Human-In-The-Loop 承認ゲート）**：検証をバイパスするような高リスク変更（`solidify`）は処理を一時停止し、人間の承認を待機。TTL 超過時は自動拒絶（Fail-Safe）。
- **HOTL（Human-On-The-Loop リアルタイム監督）**：進行中のループをいつでも一時停止／再開可能。特定遺伝子の拒否（`veto`）や方針転換（`directive`）を即座に指示可能。連続して品質低下が検出された場合は自動トリップワイヤーにより停止。

---

## ⚡ 主な機能

### 🐝 MCP 群進化（ホスト乗っ取り）
標準 MCP stdio サーバーとして動作し、ホストエディタをそのまま進化ループの実行エンジンとして統合します。エンジンが意思決定を行い、ホストが精緻なコード改修を行います。ツールには安全注記（`readOnlyHint` / `destructiveHint`）が付与されており、安全な無人運用が可能です。

### 🌉 スキルエコシステム架橋
コミュニティ既存のエージェントスキル資産（`SKILL.md`）を自動探索。**プロジェクト > ユーザー > 組み込み**の優先順位で走査し、GEP 遺伝子として自動蒸留・同期。既存スキルが即座に変異候補として活用されます。

### 📋 永続ワークフローエンジン（協調のデータ化）
複雑なソフトウェアエンジニアリング作業を、バージョン管理可能な宣言的 YAML ワークフローとして定義。エージェント作業ステップ、自動検証カスケード（ruff ➔ mypy ➔ pytest）、人間による承認ゲートをサポート。WAL（先行書き込みログ）とスナップショットにより、中断からの安全な再開が可能です。

### 🔬 厳密な対照アブレーション実験
見せかけの改善を排除する科学的検証スイート：
- **プラセボ対照（`--placebo`）**：同等長の無害な文脈を注入し、プロンプト長やロールのバイアスを排除。
- **ステージ終了規約（`--stage-exit`）**：実エピソード、対照群、固定コミット、レポート出力を満たさない限り完了と見なさない強固な規約。サンプル充足性（`MIN_N=30`）を監査し、小サンプル時は `indicative only` と明記。
- **改変防止ハーネス**：変異ロジックが自身の評価ハーネスを改ざんできないよう静的ホワイトリストで保護。

### 🧩 再帰的ハーネス工学と選択的合成（Harness2）
オンライン LLM 審査のコストを増やすことなく、*Harness2*（*arXiv:2610.14224v1*）の機械的帰属と対比合成を取り入れています：
- **4 方向コンポーネント帰属（`H2-1`）とラウンド間行動対比（`H2-5`）**：各ラウンドの編集を `helped | hurt | no_observed_effect | confounded` に自動分類し、検査遷移（`newly_passed`、`regressed`、`persistent_failures`）を算出して配信プロンプトに `[attribution]` と `[contrast]` を注入。複数コンポーネントが混在した `confounded` ラウンドが恒久遺伝子ライブラリを汚染するのを機械的に遮断します。
- **転移可能経験の三つ組とワークスペース事実の隔離（`H2-2`）**：恒久遺伝子に対して `cue + lesson + evidence` の三つ組（`--strict-transferable`）を強制し、`in this workspace:` などの局所的戦術事実はセッション限定の `WORKING_SESSION.md` に隔離（セッション終了時に自動アーカイブ・削除）。
- **`INV × DOM` 直交スコープと選択的コンポーザー（`H2-3`）**：不変条件／検証側（`INV`）とドメイン実装（`DOM`）の提案を直交分離し、競合しない `helped` 編集を機械的に合成（`compose_proposals`）するか安全に `KEEP_BASE` へフォールバック。また単一コンポーネントの救済可能バリアント（`~`）を `evolver variants` で可視化します。
- **コンポーネントコスト階層ゲート（`H2-4`）とライブラリ系譜追跡（`H2-6`）**：`Skill > Script > Subagent > Hook > Always-On Text` の静的契約検査（`validate_harness_component_integrity`）および 6 軸成果物適合性検証を実施し、$\mathcal{H}_0 + \mathcal{R}_t$ ペアライブラリ解決と `evolver meta-report` における `library_provenance`（`direct_copy / adapted / novel`）パネルを提供します。

---

## 🚀 クイックスタート

### 前提条件

- **Python >= 3.12**
- **[Git](https://git-scm.com/)**（必須：影響範囲の隔離、ステージング、アトミックなロールバックに使用）
- **[uv](https://docs.astral.sh/uv/)**（推奨される最新 Python パッケージマネージャー）

```bash
# リポジトリのクローンと依存関係の同期
git clone https://github.com/evomap/evolver.py.git
cd evolver.py
uv sync
```

### 基本操作

```bash
# 1 サイクルの進化を実行
uv run evolver run

# 自律進化デーモンループを起動
uv run evolver --loop

# レビューモード（変異後に人間の承認を待機）
uv run evolver --review

# システム健全性チェック
uv run evolver check
```

> **UI とプロキシ機能**：WebUI ダッシュボードやローカル A2A プロキシを使用する場合は、`server` エクストラを追加インストールします：
> ```bash
> uv sync --extra server
> uv run evolver webui   # http://127.0.0.1:8080 でダッシュボードを表示
> uv run evolver proxy   # ポート 8081 で A2A プロキシを起動
> ```

---

## 🛠️ ホストエージェントの接続（MCP 設定）

`evolver.py` を MCP サーバーとして設定することで、ホストエージェントが進化ループの実行器として機能します。

### 1. MCP 設定例

**Cursor**（`.cursor/mcp.json`）および **Claude Code**（`.mcp.json`）：

```json
{
  "mcpServers": {
    "evolver": {
      "command": "uv",
      "args": ["--project", "/絶対パス/to/evolver.py", "run", "evolver", "mcp"]
    }
  }
}
```

**ZCode** または仮想環境 Python を直接指定する場合：

```json
{
  "mcpServers": {
    "evolver": {
      "command": "/絶対パス/to/evolver.py/.venv/bin/python",
      "args": ["-m", "evolver.mcp_server"],
      "env": {
        "EVOLVER_SWARM_AUTO_HIJACK": "0"
      }
    }
  }
}
```

### 2. 閉ループプロトコルの流れ

接続後、ホストは標準化されたツールを通じて連携します：
1. `swarm_boot`：セッション初期化と状態報告。
2. `swarm_tick`：最新の GEP 変異プロンプトとコンテキスト（前エピソードの `[attribution]` および `[contrast]` 注記を含む）を取得。
3. `swarm_propose`*（任意）*：編集前に構造化遺伝子提案の `H2-4` コンポーネントコスト階層整合性（`check_component_integrity`）を検証、または複数の `INV × DOM` 候補提案を選択的に機械合成（`candidates`）。
4. *（ホストがエディタ上でコード差分を適用）*
5. `swarm_distill`：改修内容から構造化された Gene / Capsule を抽出（`strict_transferable` 三つ組検証および `confounded` ラウンドの自動フィルタリングに対応）。
6. `swarm_hypothesis`：検証前に当サイクルの単一仮説を宣言（任意の `expected_outcome` で通過見込みの検査を指定）。
7. `swarm_solidify`：検証ゲートを通過した改修を Git コミットとして固化し、`expected_outcome` と実検査結果を照合して `prediction_delta` を記録。
8. `swarm_feedback`：多面的評価メトリクスを返し、次サイクルの適応を支援。

前サイクルの検査出力や diff が切り詰められた場合や、コンテキスト圧縮の直前には、次の 2 ツールを併用します：
- **切り詰められた原文の参照（`episode_inspect`）**：プロンプトには上限付きの要約のみが入ります（例：`stdout truncated at 400/2208 chars; call episode_inspect to zoom in`）。推測で書き直すのではなく、具体的な質問と行範囲（例：`{"kind":"check","name":"pytest","offset_lines":0,"limit_lines":80}`）を渡して元の出力を読み戻します。`episode.json` は書き換えません。
- **圧縮前の作業メモ退避（`swarm_checkpoint_working`）**：`precompact` フックや 4 回連続の固化失敗が発生すると変異ツールが一時停止し、現在の仮説・棄却した案・主要 episode ID を `WORKING_SESSION.md`（上限 16,000 文字）に書くまで再開しません。次の `swarm_boot` が全文を返し、dispatch プロンプトは `[host_working]` 手がかりとして添付します。セッション終了時にはアーカイブ後に削除され、恒久記憶を汚しません。

### 3. ワンコマンドデモ

```bash
# 1. 確定的シミュレーション（LLM API キー不要）
uv run python examples/swarm-quickstart/demo_swarm_loop.py

# 2. 完全閉ループデモ
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py

# 3. DeepSeek を使った実機実行
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm
```

---

## 🧭 CLI コマンド体系

機能領域ごとに整理された CLI マトリクス：

| 領域 | コマンド | 説明 |
|---|---|---|
| **進化制御** | `evolver run` | 1 サイクル自己進化を実行（デフォルト） |
| | `evolver --loop` | 継続的自律進化デーモンを起動 |
| | `evolver --review` | 変異適用前に確認を挟む対話型レビューモード |
| | `evolver solidify` | 保留中の変異を検証（`--validation-scope=related\|cascade`）・コミット、または棄却パッチを復元（`--restore-stash`） |
| | `evolver round --host` | ホスト向け単一エントリ（`boot → status → tick → checklist` を一括実行） |
| | `evolver migrate-state` | リポジトリ内の旧 `memory/`・`.evolver/gep/` を外部状態ルート `~/.evolver/workspaces/<id>/` へ移行 |
| | `evolver apply-proposal` | 単一提案の適用、または複数 `INV × DOM` 提案の機械的選択合成 |
| | `evolver session` | ペア進化セッションおよび仮説管理 |
| **群・安全統制** | `evolver mcp` | stdio MCP サーバーを起動（ホスト連携口） |
| | `evolver hitl` | 人間承認ゲートの管理（`list`/`approve`/`reject`） |
| | `evolver supervise` | 人間によるリアルタイム監督（`status`/`pause`/`resume`/`veto`） |
| | `evolver setup-hooks` | Cursor / Claude Code などの IDE フックをセットアップ |
| | `evolver charter-check` | 実行環境および現行章程への適合性を検証 |
| **資産・知識** | `evolver skills` | 外部 `SKILL.md` を走査・同期して遺伝子化 |
| | `evolver distill` | LLM 応答から Gene / Capsule を蒸留（`--strict-transferable` 対応） |
| | `evolver gene-lifecycle`| 遺伝子の状態管理（`active`/`under_review`/`retired`） |
| | `evolver variants` | 棄却・保存されたバリアントアーカイブの閲覧（`*` 再配信可、`~` 意味的救済可） |
| | `evolver library` | コンテンツアドレス指定のライブラリスナップショット管理（`establish-parent`/`publish`） |
| | `evolver episode` | 過去の自己改善記録（Episode Record）の閲覧と、`episode inspect` による切り詰め原文の参照 |
| | `evolver self-report` | 自己診断を実行し、生きた記憶と防護規則を更新 |
| **ベンチマーク** | `evolver experiment` | 厳格な対照アブレーション実験を実行（`--ablation`、`--placebo`、`--stage-exit`） |
| | `evolver bench` | 凍結タスクパック、ベースライン検証、ペアライブラリスナップショット解決 |
| | `evolver anchor` | リポジトリ外の凍結アンカー検証スイートの管理・実行 |
| | `evolver gate-report` | 受け入れゲートの監視・正式採用判定レポート |
| | `evolver meta-report` | Table-8 6 軸テレメトリ、子孫変異品質、`library_provenance` 系譜レポート |
| **運用・サービス** | `evolver check` / `watch`| システム診断とバックグラウンド監視 |
| | `evolver start` / `stop` | プラットフォーム共通デーモンライフサイクル管理 |
| | `evolver webui` | 可視化ダッシュボードを起動（`server` 必要） |
| | `evolver proxy` | A2A 分散プロキシを起動（`server` 必要） |

---

## 🔒 セキュリティモデルと防御機構

`evolver.py` はコードを自律改修するため、堅牢な安全防壁を標準装備しています：

- **Git 爆発半径の制御**：すべての改修は Git 管理下で実施。変異前に `git stash` による退避を行い、遺伝子ごとに最大ファイル数（`constraints.max_files`）や禁止パス（`forbidden_paths`）を制限。ゲート不合格時は即座にアトミックにロールバック。
- **コンテンツアドレス指定とハッシュ検証**：資産 ID に SHA-256 ダイジェスト（`sha256:...`）を組み込み、改ざんや破損を読み込み時に自動検出・排除。
- **秘密情報の自動マスク**：API キー、JWT、秘密鍵、パスワードを検出し、プロンプト保存やログ出力、WebUI 送信前に自動的にマスク。
- **OS レベルの排他ロック**：OS ネイティブのインスタンスロック機構により、同一リポジトリに対する複数デーモンの同時書き込みや状態競合を確実に防止。

---

## 🗺️ プロジェクト構造

```
src/evolver/
├── cli.py                  # CLI エントリーポイント、引数構文解析、コマンド配信
├── config.py               # 集中設定、閾値管理、環境変数マッピング
├── swarm.py                # 群プロトコル：接管プロンプト生成と閉ループディスパッチ
├── mcp_server.py           # stdio MCP サーバー実装（ツール・リソース・プロンプト）
├── evolve/                 # 進化オーケストレーター
│   ├── runner.py           # サイクル制御およびデーモンループ実行
│   ├── guards.py           # 実行前検査（負荷、メモリ、システム健全性）
│   └── pipeline/           # 非同期 7 段階進化パイプライン（Collect 〜 Dispatch）
├── gep/                    # GEP（ゲノム進化プロトコル）コア
│   ├── schemas/            # Pydantic モデル定義（Gene、Capsule、Task など）
│   ├── episode_record.py   # コンテンツアドレス指定 Episode Record、4 方向帰属・対比差分
│   ├── working_memory.py   # セッション限定 WORKING_SESSION.md とワークスペース事実隔離
│   ├── record_route.py     # 双方向記録ルートと INV × DOM 直交スコープ検証
│   ├── proposal.py         # 構造化遺伝子提案と機械的選択コンポーザー
│   ├── policy_check.py     # 安全ポリシー、コスト階層ゲート、6 軸成果物適合性検査
│   ├── variant_archive.py  # DGM 式棄却バリアントアーカイブと単一コンポーネント救済
│   ├── library.py          # コンテンツアドレス指定ライブラリスナップショット
│   ├── asset_store.py      # レイヤード JSON/JSONL 資産永続化
│   ├── hitl.py             # 人間承認ゲート（HITL）
│   ├── supervision.py      # リアルタイム監督と自動停止トリップワイヤー（HOTL）
│   ├── skill_assets.py     # スキルエコシステム連携と遺伝子蒸留
│   ├── gene_lifecycle.py   # 遺伝子ライフサイクル状態機械
│   └── solidify.py         # 変異適用、検証ゲート、Git コミット
├── bench/                  # 凍結タスクパック、評価器、統計検定
├── experiment/             # 対照アブレーション実験スイート（プラセボ対照、サンプル充足性）
├── adapters/               # 各種 IDE 連携フック（Cursor、Claude Code、Codex）
├── proxy/                  # ローカル A2A プロキシとモデルルーティング
└── webui/                  # 読み取り専用ダッシュボードおよび SSE イベント配信
```

---

## 📚 関連資料

- **[ステップバイステップ実践チュートリアル（tutorials/）](tutorials/README.md)**：専門用語に頼らず、具体例と実験から `evolver.py` の仕組みを解き明かす全 5 回の実践ガイド（中国語）。
- **[演进方案.md](演进方案.md)**：現行章程。「経験こそが証拠」への転換を論理づける設計文書（中国語）。
- **[TODO_VISTA.md](TODO_VISTA.md) & [TODO_HARNESS2.md](TODO_HARNESS2.md)**：VISTA（現場再注視・圧縮ゲート）および Harness2（`H2-1`..`H2-6` 帰属・事実隔離・選択的合成）の機械的ハーネス実装リスト。
- **[AGENTS.md](AGENTS.md)**：AI エージェント開発者向けの実装規約、注意点、設計指針。
- **[DEBUG.md](DEBUG.md)**：排他制御やエッジケースに対処するためのトラブルシューティング手引き。
- **[CHANGELOG.md](CHANGELOG.md)**：詳細な変更履歴。
- **[CONTRIBUTING.md](CONTRIBUTING.md)**：開発参加とテスト規約。

---

## 📄 ライセンス

本プロジェクトは [Apache License 2.0](LICENSE) のもとで公開されています。

> **系譜に関する注記**：`evolver.py` は、公開仕様とテスト規約に基づき独自に開発されたクリーンルーム Python 実装です。原案の概念は EvoMap 組織の成果に端を発しており、本リポジトリは Apache-2.0 ライセンスにより独立して保守・配布されています。
