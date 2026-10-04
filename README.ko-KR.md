# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[English](README.md) · [简体中文](README.zh.md) · [日本語](README.ja-JP.md) · **한국어**

**GEP 기반 AI 에이전트 자기 진화 엔진.**

엔진은 LLM을 호출하지 않는다. MCP stdio로 연결된 호스트 Agent가 실행기다. 현재 단계는 그 루프를 동결된 외부 태스크 팩으로 향하게 한다. 헌장은 [演进方案.md](演进方案.md)(중국어). 이 트리는 `@evomap/evolver`의 행동 등가 Python 포트로, 다음 기반을 사용한다:

- **Python 3.12+** — `asyncio`, 타입 파라미터 문법(`list[str]`), `tomllib`
- **uv** — 빠른 Python 패키지 관리
- **Pydantic v2** — 스키마 검증과 설정
- **httpx** — 비동기 HTTP 클라이언트(Node의 `undici` 상당)
- **FastAPI + uvicorn** — 로컬 Proxy와 WebUI(선택적 `server` extra)

> **참고**: GEP 코어, 진화 파이프라인, Proxy 라우트, 인지 편성은 대체로 구현되어 있다. ATP 상업 루프와 Validator 샌드박스는 여전히 부분적이며 현재 단계의 대상이 아니다.

---

## 빠른 시작

```bash
# 의존성 설치 (프로젝트 로컬 환경)
uv sync

# 단일 진화 사이클
uv run evolver

# 데몬 루프
uv run evolver --loop

# 리뷰 모드
uv run evolver --review

# WebUI 대시보드 (server extra 필요)
uv run evolver webui

# 로컬 A2A 프록시
uv run evolver proxy
```

> WebUI와 로컬 Proxy에는 server extra가 필요하다: `uv sync --extra server`. 핵심 진화 엔진과 MCP 서버에는 fastapi 의존성이 없다.

**호스트 Agent를 군집에 참여시키기 (v1.98+ 플래그십)** — 엔진이 MCP stdio로 호스트를 인수해 GEP 변이 프롬프트의 실행기로 만든다. 한 명령으로 전체 루프를 체험:

```bash
uv run python examples/swarm-quickstart/demo_swarm_loop.py            # 결정적 데모 (LLM 불필요)
uv run python examples/swarm-quickstart/demo_closed_loop_flash.py     # 폐쇄 루프 전체
DEEPSEEK_API_KEY=sk-... uv run python examples/swarm-quickstart/demo_swarm_loop.py --llm   # DeepSeek가 실제 실행
```

자세한 내용은 [MCP 군집 진화](#mcp-군집-진화)와 [examples/swarm-quickstart/](examples/swarm-quickstart/) 참조.

### uvx (원샷 / 프로젝트 설치 없이)

evolver가 공개된 후(또는 `uv sync` 없이 도구 격리를 원할 때):

```bash
# PyPI에서 (공개 후)
uvx evolver --help
uvx evolver run

# 로컬 체크아웃에서 (전역 설치 없음)
uvx --from . evolver run
uvx --from . evolver --loop
```

### 런처 선택

데몬 재시작, 라이프사이클 `start`, IDE hooks는 `EVOLVER_LAUNCHER`로 재호출 방법을 결정한다:

| 값 | 동작 |
|---|---|
| `auto` (기본) | `uv` + 프로젝트 루트가 있으면 `uv run evolver`, 없으면 `uvx`, 그것도 없으면 `python -m evolver` |
| `uv` | `uv run [--project <root>] evolver …` 강제 |
| `uvx` | `uvx [--from <root>] evolver …` 강제 (`uvx` 셔미 없으면 `uv tool run`) |
| `python` | `python -m evolver …` 강제 |

감독자는 `EVOLVER_LOOP_COMMAND`(공백 구분)로 argv 전체를 덮어쓸 수 있다.

## MCP 군집 진화

stdio MCP 서버를 통해 evolver는 **호스트 Agent를 GEP 변이 프롬프트의 실행기**로 만든다. 엔진 자체는 LLM API를 호출하지 않으며, 연결된 호스트(ZCode / Claude Code / Cursor / …)가 곧 실행기다(v1.98.0+).

### 호스트 연결 설정

실행 명령은 `uv run evolver mcp`(프로젝트 내부) 또는 `<venv>/bin/python -m evolver.mcp_server`(절대 경로 — 호스트 설정에 권장) 중 하나다.

**ZCode** (워크스페이스/사용자 `settings`의 `mcpServers`):

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

**Claude Code**(프로젝트 루트 `.mcp.json`)와 **Cursor**(`.cursor/mcp.json`)도 동일한 형태다. 완성된 설정은 [`examples/swarm-quickstart/mcp-host-configs/`](examples/swarm-quickstart/mcp-host-configs/).

> 자주 쓰는 환경 변수: `EVOLVER_SWARM_AUTO_HIJACK=1` (HITL을 강제로 켜고 호스트 중계 승인을 거부. 상주 instructions는 불변); `EVOLVER_HITL_MODE=on` (고위험 solidify에 인간 승인 필요); `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` (연속 저하 피드백 N회 시 자동 일시정지, 기본 3).

### 인수와 폐쇄 루프

- **주입**: 이 메시지에 이미 다른 태스크가 있으면 그 태스크를 수행. 없으면 `swarm_boot`를 호출하고 실제 상태를 한 문장으로 말한다. `boot_once`는 세션 등록만 하며 부팅 시 스킬 동기화는 하지 않는다. 동결 팩 또는 Parent 베이스라인이 없거나 루프가 일시정지 중이면 tick하지 않는다(사람이 `EVOLVER_SWARM_GATE_HANDOFF=hotl`로 앞의 두 항목을 건너뛸 수 있으나 게이트는 계속 게시를 거부). "그만", "계속"이라고 하면 호스트가 `swarm_supervise` pause / resume을 중계한다. 최초 준비(동결 팩, 다른 컨텍스트에서 val 개봉, 베이스라인 생성)는 [examples/swarm-quickstart/README.md](examples/swarm-quickstart/README.md)에 있다. 전체 프로토콜은 MCP 프롬프트 `evolver_swarm`과 `swarm_boot`의 반환에 있다
- **폐쇄 루프 절차**: `swarm_tick`(GEP 변이 프롬프트 획득)→ 호스트가 자신의 편집 도구로 변이 실행 → `swarm_distill`(Gene/Capsule 증류)→ `swarm_hypothesis`(단일 가설 게이트: 호스트가 해당 라운드의 유일한 가설을 선언. 없으면 거부)→ `swarm_solidify`(검증 게이트 + 고체화)→ `swarm_feedback`(통합 평가 신호 E, 저점수는 repair-bias 자동 주입)→ 루프. `swarm_propose`로 증거 팩에서 개입 제안, `swarm_report`는 하트비트다
- **이중 안전 게이트**: HITL 승인 게이트(`evolver hitl list|approve|reject`, TTL 만료 시 fail-safe로 REJECT) + HOTL 감독(`evolver supervise status|pause|resume|direct|veto|unveto` — 사람은 언제든 브레이크/거부/전환 가능)

### Hooks 연동 (신호 자동 수집)

호스트가 파일 hooks를 지원하면 설치한다. 세션 경계와 도구 출력의 오류 신호가 자동으로 진화 기억으로 흐른다:

```bash
uv run evolver setup-hooks --platform auto --project-dir /path/to/workspace
# 플랫폼: cursor | claude-code | codex | kiro | opencode | vscode | generic | auto
```

MCP 전용 호스트(파일 hooks 능력 없음)는 **프로세스 내 브리지**를 쓴다: 세션 시작/종료 시 그리고 오류 출력을 관측할 때 `swarm_hook_event`를 호출(`event=session_start|session_end|signal_detect`, `payload.content`에 본문). 감지된 신호(`log_error` / `perf_bottleneck` / …)는 다음 사이클의 유전자 선택에 바로 주입된다. 호스트가 `swarm_hooks`(`action=status|install|uninstall`)로 파일 hooks를 직접 설치할 수도 있다.

### MCP 리소스와 도구 주석

도구 외에 4개의 읽기 전용 리소스를 노출한다(호스트는 구독하거나 도구 왕복 없이 읽을 수 있다):

| URI | 내용 |
|---|---|
| `evolver://status` | 실시간 엔진/군집 상태 (JSON, HITL/HOTL/피드백 요약 포함) |
| `evolver://instrument-prompt` | 현재 렌더링된 인수 프롬프트 |
| `evolver://dispatch/last` | 최근 GEP 변이 프롬프트 (`last_prompt.md`) |
| `evolver://events/recent` | 최근 진화 사이클 타임라인 (JSON) |

도구 면은 26개: 범용 8개(`asset_search`, `asset_get`, `episode_get`, `mailbox_send`, `mailbox_poll`, `mailbox_ack`, `rebuild_views`, `cycle_timeline`) + 군집 18개(`swarm_boot` / `tick` / `distill` / `hypothesis` / `propose` / `solidify` / `feedback` / `report` / `status` / `approvals` / `approval_resolve` / `supervise` / `hooks` / `hook_event` / `skills` / `workflow_run` / `workflow_act` / `workflow_status`).

도구에는 MCP 사양 주석이 붙는다: `swarm_status`, `swarm_approvals`, `asset_search`, `episode_get`, `cycle_timeline` 등은 `readOnlyHint`(플랜 모드에서 확인 생략 가능); `swarm_solidify`, `swarm_hypothesis`, `swarm_propose`, `swarm_supervise`, `swarm_approval_resolve`, `swarm_workflow_act`는 `destructiveHint`(호스트가 사용자 확인을 요청할 수 있다).

### 스킬 생태 브리지 (SKILL.md → 스킬 유전자)

호스트 생태의 스킬 파일을 진화 엔진에 연결한다(EvoX SkillRegistry 패턴: **project > user > builtin 우선순위, 동명 차폐**). 탐지 루트: 워크스페이스 `.agents/skills`와 `.claude/skills` > 사용자 `~/.agents/skills`, `~/.zcode/skills`, `~/.claude/skills` > 엔진 내장(`EVOLVER_SKILL_ROOTS`로 덮어쓰기, 순서 = 우선순위).

```bash
uv run evolver skills scan              # 발견 결과 미리보기 (우선순위·차폐 포함)
uv run evolver skills sync --dry-run    # 설치될 스킬 유전자 미리보기
uv run evolver skills sync              # GEP 자산 저장소로 변환 (gene_distilled_s2g-*)
uv run evolver skills list              # 저장소의 스킬 유전자 목록
```

동기화되면 스킬은 유전자로서 신호 매칭과 선택에 참여한다 — 예를 들어 "ImportError 수정" 스킬은 신호가 맞으면 GEP 프롬프트에 선정된다. 호스트는 MCP `swarm_skills`(`scan|list|sync`)로도 직접 조작할 수 있다.

### 진화 워크플로 (EvoX 수확: 협업을 데이터로)

협업 전체를 **YAML 워크플로**로 표현한다(diff 가능 → 진화 가능): `agent` 스텝은 `role`/`instruction`을 선언해 호스트 실행기가 담당, `gate` 스텝은 검증 캐스케이드(ruff→mypy→pytest)를 엔진 측에서 실행, `approval` 스텝은 인간 승인 게이트에 안착 — 전체가 WAL 영속·재개 가능(Sprint 24.10 엔진 + v1.110.0 확장).

```bash
uv run evolver workflow templates                  # 동봉 템플릿: repair / innovate
uv run evolver workflow run --template repair      # 복구 루프 시작 (YAML 파일도 가능)
uv run evolver workflow awaiting <id>              # 호스트 실행기 / 승인자의 현재 담당
uv run evolver workflow complete <id> --result '{"ok": true, "files": 2}'
uv run evolver workflow approve <id>               # 승인 후 해제
```

MCP 측: `swarm_workflow_run`(파일 또는 템플릿으로 시작), `swarm_workflow_act`(approve/reject/complete/resume/cancel), `swarm_workflow_status`(전체 상태 + 호스트 담당).

### 통제 실험과 소거 판정

소거 벤치마크는 과거 에피소드 기록이 호스트 자가 복구를 실제로 개선하는지 검증한다(SelfSearch 프로토콜, arXiv:2609.37968v2). 자체 주장 점수 향상이 아니라 엄격한 오프라인/온라인 통제 평가 하네스를 제공한다:

```bash
# 과거 기록 유무에 따른 태스크 성능 대조 (실제 LLM 블라인드 테스트)
uv run evolver experiment --ablation --tasks tasks.json \
    --from-episodes --placebo --model deepseek-flash --output result.json
```

핵심 과학적 안전장치:
- **플라세보 대조(`--placebo`)**: 기록 없는 암에 동일 길이의 중립 블록을 주어 프롬프트 존재 편향을 배제한다. 차이는 기록의 *내용*만 평가한다.
- **단계 출구 계약(`--stage-exit`)**: 출구를 기계적으로 강제 — 실제 에피소드 + 플라세보 + 고유 태스크 + 확정 커밋 + 리포트 저장, 하나라도 없으면 exit 2로 리포트를 내지 않는다. 시드 AB/BA 교차 배치, 호출별 기록(지연, 토큰 3분할, 오류 분류, served model), 태스크별 대응 정확 검정, 샘플링 고정, 서버 사이드 프롬프트 불균형 계측이 리포트에 동봉된다.
- **표본 충족성 감사**: `MIN_N=30`과 대조. 힘이 부족한 표본은 결론에 자동으로 `indicative only`를 명시한다.
- **귀속 투명성**: 성공률의 실질 향상(`success_rate`)과 토크 동수 타이브레이크(`tokens_only`)를 엄격히 구분한다.
- **호출 그래프 경계 가드**: 에피소드 기록기는 유닛 테스트로 전 `src/`를 스캔하여(`test_the_record_writer_is_confined_to_a_declared_boundary`) 변이·벤치 러너가 스스로를 기록·채점할 수 없게 한다.

## 필요 조건

- **[Python](https://python.org/)** >= 3.12
- **[Git](https://git-scm.com/)** — 필수. 롤백, 폭발 반경 계산, 고체화에 git을 사용한다. git이 아닌 디렉터리에서는 명확한 오류로 실패한다.
- **[uv](https://docs.astral.sh/uv/)** — 권장. `uv sync`, `uv run`, `uvx` 사용 가능. 표준 `pip` / `python -m`도 동작한다.

## CLI 명령 참조

| 명령 | 설명 |
|---|---|
| `run` | 단일 진화 사이클 (기본) |
| `--loop` / `--solo` / `--review` | 데몬 루프 / 완전 오프라인(`--loop` 내포) / 인간 리뷰로 정지 |
| `start` `stop` `restart` `status` `log` | 데몬 라이프사이클 |
| `check` `watch` | 헬스 체크와 헬스 감시 |
| `solidify` | 보류 중인 변이(또는 제안) 적용 |
| `apply-proposal` | 유전자 제안 JSON 기계 적용(앵커 검증됨, 워크스페이스 안전) |
| `review` | 보류 solidify 리뷰 |
| `report` | 사이클 판정 리포트(부정 결과도 그대로) + 패턴 투영 |
| `gate-report` | 수용 게이트 soak 리포트: shadow 지표 + 승격 판정 |
| `variants` | 거부되었으나 보존된 후보의 변이 보관소(RSI P1-3) |
| `charter-check` | 기계 영수증: 헌장 준수와 드리프트 검증 |
| `anchor init\|list\|run` | 트리 밖 앵커 스위트: 동결 검증 계약(RSI P0-1) |
| `meta-report` | 개선 기구 텔레메트리: RSI Table-8 패널 + 자손 품질 |
| `gene-lifecycle list\|evaluate\|reinstate` | 유전자 라이프사이클 거버넌스(active / under_review / retired) |
| `soak setup\|exports\|status` | 진화 런타임 상태를 git 트리 밖에 유지 |
| `session start\|resume\|status\|round\|hypothesize\|reject\|accept\|incomplete\|extend\|finalize` | 페어 진화 세션(라운드 예산은 시작 시 8에서 동결; `extend`는 인간만) |
| `self-report` | Autopoiesis 자가 진단과 규칙 진화 |
| `bench list\|init\|freeze\|gate\|baseline\|run\|prompt\|grade\|compare` | 태스크 팩, Parent 베이스라인, `--library` 포함 풀이 프롬프트, 대응 비교 |
| `library establish-parent` | Parent 라이브러리 스냅샷 최초 기록(solidify는 도달 불가) |
| `episode list\|show` | 에피소드 기록 — 자기 개선 1라운드의 런타임 기록 |
| `exec` `distill` `fetch` `reuse` `publish` `sync` `asset-log` `replay` `rebuild-views` | 실행 브리지, LLM 출력 증류, Hub 가져오기/재사용/게시, 자산 호출 로그, SQLite 리플레이, 파생 뷰 |
| `skill2recipe` | 검증된 스킬을 게시 가능한 GEP 레시피로 합성 |
| `mcp` | MCP 서버를 stdio로 실행 (군집 진입점) |
| `hitl list\|approve\|reject` | HITL 승인 게이트 |
| `supervise status\|pause\|resume\|direct\|veto\|unveto` | HOTL 감독 |
| `skills list\|scan\|sync` | 스킬 생태 브리지 |
| `workflow run\|templates\|status\|awaiting\|approve\|reject\|complete\|resume` | 내구 워크플로 엔진 |
| `experiment --ablation …` | 통제 실험 / 소거 판정 |
| `webui` `login` `logout` `webui-token` `reset-local-secret` `setup-hooks` `trajectory` | 대시보드, OAuth, 토큰, IDE hooks, 트레이스→궤적 내보내기 |
| `atp` `atp-complete` `buy` `orders` `verify` | ATP 로컬 정산, auto-buyer 동의, 주문 |
| `proxy` `proxy-token` | A2A 프록시와 로컬 bearer 토큰 |
| `recipe list\|show\|apply\|cache-list\|cache-clear` | 레시피 허브 |

각 서브커맨드는 `--help`로 전체 플래그를 지원한다.

## 프로젝트 구조

```
src/evolver/
├── cli.py              # CLI 진입점 (argparse), .env 로딩, 명령 분배
├── config.py           # 런타임 임계값 + 환경 변수
├── canary.py           # 포크 카나리: CLI가 크래시 없이 로드되는지 검증
├── swarm.py            # 군집 코어: 인수 프롬프트 + 루프 도구
│                       #   (tick/distill/hypothesis/propose/solidify/feedback/
│                       #    report/status/supervise/hooks/hook_event/skills),
│                       #   stdout 전체 포착
├── mcp_server.py       # MCP stdio 서버: 범용 8 + 군집 18 도구,
│                       #   evolver_swarm 프롬프트, evolver://* 리소스,
│                       #   도구 주석 (mcp>=2.0 MCPServer)
├── evolve/
│   ├── runner.py       # 사이클 편성 (단일 + 데몬 루프)
│   ├── guards.py       # 이륙 전 체크 (부하, RSS, 쿨다운)
│   ├── post_cycle.py   # 사이클 후 훅 (ATP auto-buyer)
│   └── pipeline/       # 7단계 파이프라인 + preflight (비동기 함수)
│       ├── collect.py      # 로그 스캔 + living_memory
│       ├── signals.py      # 신호 + guard/preflight/learning
│       ├── hub.py          # Hub 쿼리
│       ├── enrich.py       # 기억 조언 + 양방향 메모리 동기화
│       ├── autopoiesis.py  # SelfReport + 항상성 + 생존 가능성
│       ├── select.py       # Gene/Capsule 선택 + 혁신 기록
│       └── dispatch.py     # GEP 프롬프트 + solidify 상태 저장
├── gep/                # GEP(게놈 진화 프로토콜) 코어
│   ├── schemas/        # Pydantic 모델: Gene, Capsule, Task, Protocol
│   ├── asset_store.py  # JSON/JSONL 영속화 (오버레이 의미론)
│   ├── cognition.py    # 인지 편성 (recall/explore/curriculum/reflection)
│   ├── solidify.py     # 유전자 적용 → 검증 → 영속화 → 게시
│   ├── selector.py     # 신호 매칭 + 후성유전학 편향
│   ├── signals.py      # 신호 수집과 분류
│   ├── feedback.py     # 통합 평가 신호 E (EvoX 수확)
│   ├── hitl.py         # HITL 승인 게이트 (만료 시 fail-safe로 REJECT)
│   ├── supervision.py  # HOTL 오버레이 (pause/veto/directive + 트립와이어)
│   ├── skill_assets.py # SKILL.md 브리지 (project > user > builtin)
│   ├── episode_record.py   # 에피소드 기록: 자기 개선 1회의 런타임 기록
│   ├── evolution_session.py# 페어 세션 기계(§5.1) + 단일 가설 게이트
│   ├── library.py      # 콘텐츠 주소 라이브러리 스냅샷
│   ├── bench/          # 동결 태스크 팩, 채점, 동결 게이트, 대응 검정
│   ├── validator/      # 샌드박스 실행기, 리포터, 스테이크 부트스트랩
│   └── ...             # 100+ 모듈
├── proxy/              # 로컬 HTTP 프록시 (기본 127.0.0.1:8081, 라우트 /v1/a2a)
│   ├── server/routes.py    # FastAPI 라우트 매트릭스 (task/ATP/extensions)
│   ├── router/             # LLM 라우팅, 기능, SSE 스트리밍
│   ├── extensions/         # DM, 세션, 스킬 업데이터, 트레이스 제어
│   ├── mailbox/store.py    # 로컬 메일박스 JSONL 저장
│   ├── sync/               # Hub 양방향 동기화 엔진
│   └── lifecycle/manager.py# 프록시 라이프사이클 + 하트비트
├── atp/                # Agent 거래 프로토콜 마켓플레이스
│   ├── protocol.py         # 열거형과 Pydantic 모델
│   ├── auto_buyer.py       # 능력 격차 자동 발견 (옵트인, 예산 제한)
│   ├── auto_deliver.py     # 태스크 자동 수령·납품
│   └── settlement.py       # 로컬 원장
├── adapters/           # IDE 통합 훅
│   ├── hook_adapter.py     # 공유 어댑터 로직
│   ├── setup_hooks.py      # Cursor / Claude Code / Codex / Kiro / OpenCode 훅
│   └── scripts/            # 런타임 스크립트 (session_start, signal_detect)
├── ops/                # 운영 (라이프사이클, 헬스, 자가 수리, soak 환경)
│   ├── lifecycle.py        # 크로스 플랫폼 데몬 관리
│   ├── health_check.py     # 디스크/메모리/프로세스 점검
│   └── self_repair.py      # Git 긴급 수리
├── bench/              # 워크스페이스 벤치마크 (헬스 태스크 + fitness 원장)
├── experiment/         # 통제 실험, 실제 LLM 소거, 플라세보 암, 지표
├── recipe/             # 레시피 허브 (list/show/apply + 캐시)
├── solo/               # 제약 오프라인 모드 (네트워크/ATP/Validator 차단)
└── webui/              # FastAPI 읽기 전용 대시보드
    ├── app.py            # 대시보드 + SSE `/events/stream`
    ├── dashboard.py      # 자체 완결 다크 HTML 대시보드 (실시간 이벤트)
    ├── client/           # 인라인 JS/CSS (SSE, bootstrap, i18n)
    └── observer/         # 데이터 집계 모듈

tests/                  # 테스트 파일 342개, 테스트 4,227개 (pytest; MCP 프로토콜
                        #   E2E와 tests/e2e/의 실 LLM 루프 E2E 포함)
scripts/                # CLI 헬퍼 스크립트 23개 ("스크립트" 절 참조)
src/evolver/assets/gep/ # 시드 유전자 라이브러리
memory/                 # 런타임 데이터 (graph JSONL, reviews JSONL)
```

## 환경 변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | 사용자별 런타임 상태 디렉터리 |
| `EVOLVER_REPO_ROOT` | 자동 감지 | 저장소 루트 덮어쓰기 |
| `OPENCLAW_WORKSPACE` | (없음) | 워크스페이스 루트 덮어쓰기 |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP 자산 저장소 |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | 진화 상태 |
| `EVOLVER_SESSION_SCOPE` | (없음) | 프로젝트별 상태 격리 세그먼트 |
| `EVOLVE_STRATEGY` | `balanced` | 진화 전략 프리셋 |
| `EVOLVE_BRIDGE` | auto | Git worktree 변이 브리지 |
| `EVOLVER_ROLLBACK_MODE` | `stash` | 롤백 전략: stash / hard / none |
| `EVOLVER_MAX_CYCLES_PER_PROCESS` | `0` (무제한) | 데몬 프로세스당 최대 사이클 |
| `EVOLVER_CYCLE_TIMEOUT_MS` | `2700000` | 사이클 1회 하드 타임아웃 |
| `EVOLVER_VALIDATOR_ENABLED` | 옵트인 (`1`/`true`로 활성화) | Validator 데몬 |
| `EVOLVER_WEBUI_PORT` | `8080` | WebUI 포트 |
| `EVOLVER_PROXY_PORT` | `8081` | 로컬 프록시 포트(`EVOMAP_PROXY_PORT` 별칭); `evolver proxy --port`로 덮어쓰기 |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub URL |
| `A2A_NODE_ID` | 자동 생성 | 노드 식별 |
| `GITHUB_TOKEN` | — | GitHub API 토큰 |
| `EVOLVER_HITL_MODE` | `off` | HITL 승인 게이트 — `on`이면 고위험 solidify는 인간 승인 대기(off도 감사 기록; 미지 값은 fail-closed로 on) |
| `EVOLVER_HITL_TTL_MS` | `1800000` | HITL 보류 요청 TTL — 만료 시 fail-safe로 REJECT |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL 트립와이어 — 연속 N회 저하 시 자동 일시정지(`0`이면 비활성) |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | 군집 피드백 저하 임계값 — 미만(또는 `success=false`)이면 repair-bias 주입 |
| `EVOLVER_ADAPTIVE_MUTATION` | `true` | 피드백 기반 변이 카테고리 가중치 적응 |
| `EVOLVER_ADAPTIVE_MUTATION_SHIFT` | `0.2` | 적응 가중치 이동 폭 (정규화 전) |
| `EVOLVER_SWARM_AUTO_HIJACK` | `false` | `1`이면 HITL 강제 및 호스트 중계 승인 거부. 상주 instructions 불변 |
| `EVOLVER_SWARM_GATE_HANDOFF` | `human` | 동결 팩/베이스라인 부재 시: `human`은 boot/tick을 `await_human`으로; `hotl`은 tick 계속(게이트는 계속 거부·롤백하며 아무것도 게시하지 않음) |
| `EVOLVER_SKILL_ROOTS` | 3계층 루트 | 스킬 루트 덮어쓰기(os.pathsep 구분, 순서 = 우선순위) |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | 승격 판정 최소 gated 표본 수(false-kill 상한 0.1, 차단율 구간 0.05–0.5는 코드 상수) |
| `EVOLVER_ACCEPTANCE_SHADOW` | `true` | shadow 모드: 판정은 측정만, 집행 안 함. `0`으로의 전환은 인간의 결정 |
| `EVOLVER_FITNESS_GATE_ENFORCE` | 꺼짐 | `no_improvement` 변이를 보고만 하지 않고 롤백 |
| `EVOLVER_GENE_INERT_BAN_STREAK` | `8` | 비활성 유전자가 연속 N라운드 무결과 후 선택 금지 |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | 적용 완료 유전자 쿨다운 창 — 최근 성공 고체화는 선택 점수 감점 |
| `EVOLVER_APPLIED_GENE_COOLDOWN_PENALTY` | `0.25` | 쿨다운 감점 계수(금지 아님 — 단독 일치는 여전히 선택 가능) |
| `EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB` | `100` | memory_graph.jsonl 로테이션 임계값 |
| `EVOLVER_MEMORY_GRAPH_RETENTION_COUNT` | `7` | 보존할 로테이션 보관 수 (`0`이면 전부 삭제) |
| `EVOLVER_MEMORY_GRAPH_AUTO_ROTATE` | `true` | `false`/`0`/`no`로 자동 로테이션 비활성화 |
| `EVOLVER_ROTATE_GZIP_MAX_MB` | `32` | 초과 시 rename만 (gzip 안 함 — OOM 방지) |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | 남용 방지 텔레메트리 (`heartbeat`/`off`) |
| `EVOLVER_OUTCOME_REPORT` | `off` | 재사용 결과를 Hub에 보고해 귀속 획득 |
| `EVOLVER_REUSE_ATTRIBUTION` | `off` | 재사용 귀속 모드 |
| `EVOLVER_EVAL_WORKTREE_STRICT` | 꺼짐 | 평가 worktree 실패 시: `1`이면 라이브 cwd로 폴백하지 않고 실패 |
| `EVOLVER_AUTOPOIESIS` / `EVOLVER_AUTOPOIESIS_WRITE` | `1` / `1` | Autopoiesis 페이즈 / 규칙과 살아있는 기억 영속화(`0`=dry-run) |
| `EVOLVER_LEARNING_SIGNALS` | `1` | 환경 학습 신호 주입 |
| `EVOLVER_LAUNCHER` | `auto` | 재호출 런처: `auto` / `uv` / `uvx` / `python` |
| `EVOLVER_LOOP_COMMAND` | (없음) | 데몬 루프 명령의 argv 전체 덮어쓰기 |
| `EVOLVER_FF_*` | 플래그별 | 기능 플래그(`EVOLVER_FF_ENABLE_RECALL_INJECT`, `_REFLECTION`, `_EXPLORE`, `_CURRICULUM`, `_SKILL_AUTO_UPDATE` 등) — 환경 변수가 디스크 플래그 저장보다 우선 |

## 구현 상태

> **총평** (2026-10-04): 패키지 버전 **1.113.0**. 페어 세션은 2026-09-27에 마무리되었고, 밀봉 val에서 Parent를 넘은 후보는 없었다. 현재 헌장은 [演进方案.md](演进方案.md): 경험을 증거로. 출구는 기록 유무 소거 판정이며, n=3 합성 기록은 indicative only다. 수용 게이트는 shadow 유지. 아래 백분율은 2026-09-05 스냅샷이다.

| 하위 시스템 | 상태 | 비고 |
|---|---|---|
| **GEP 데이터 레이어** | ~90% | 시드 유전자 11×sha256; solidify 직접 테스트 + 학습 헬퍼 |
| **GEP 인지** | ~80% | recall/reflection/distill; explore/curriculum 플래그 제어 |
| **진화 파이프라인** | ~90% | 7 페이즈 + Autopoiesis + 하드 타임아웃; 적용 완료 유전자 쿨다운(v1.111) |
| **MCP 군집 진화** | ~97% | 인수 루프 + E 피드백 + HITL/HOTL + Hooks/스킬 브리지 + 워크플로 도구; dogfood는 round-78까지 |
| **워크플로 엔진** | ~90% | WAL 영속 스텝(script/foreach/if/agent/approval/gate); YAML + 롤 + 템플릿(v1.110) |
| **수용 게이트** | ~85% | shadow soak + gate-report 판정; 강제 집행 스위치는 인간 결정 |
| **프록시 인프라** | ~85% | 멀티 프로바이더, 토큰 재사용, 경로 CLI 플래그, 포트 **8081** |
| **ATP 마켓** | ~65% | 로컬 정산; Hub 상용 E2E 보류 |
| **IDE 어댑터** | ~85% | 런타임 훅 + py_compile 가드 + MCP 인프로세스 브리지 |
| **Ops / Solo** | ~85% | 라이프사이클, force-update, `--solo` |
| **WebUI** | ~70% | SSR 대시보드 + GitHub observer |
| **Validator** | ~50% | 샌드박스 기반; 프로덕션 네트워크 격리 보류 |
| **문서 / 릴리스** | ~90% | CHANGELOG + 버전 **1.113.0**; 멀티 OS CI(Windows는 blocking + 앵커 스위트) |

진행 중인 계획은 [演进方案.md](演进方案.md)와 [TODO.md](TODO.md). wikiskill 감사는 사료다.

## 예제

| 예제 | 설명 |
|---|---|
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **군집 진화 전체 루프** — MCP 인수, tick→실행→distill→solidify→feedback, HITL/HOTL 운영(`--llm`으로 DeepSeek가 실행기; `demo_closed_loop_flash.py`로 전체 실행) |
| [`examples/hello-world/`](examples/hello-world/) | 격리 워크스페이스에서 단일 진화 사이클 |
| [`examples/daemon-loop/`](examples/daemon-loop/) | 상주 데몬, 라이프사이클 관리, start/stop/status/log |
| [`examples/proxy-basics/`](examples/proxy-basics/) | A2A 프록시, proxy-token, curl API 예제, LLM 중계 |
| [`examples/ide-hooks/`](examples/ide-hooks/) | Cursor / Claude Code / OpenCode / Codex 세션 훅 |
| [`examples/solo-mode/`](examples/solo-mode/) | 완전 오프라인 격리 모드 |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis 자가 진단, 교훈, 자생 규칙 |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | 증류 → 재사용 → 게시 자산 생명주기 |
| [`examples/skill2recipe/`](examples/skill2recipe/) | Agent 스킬을 GEP 레시피로 합성 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP 주문/납품/하트비트 데모 (Hub 모킹 가능) |

## 테스트

```bash
# 전체 테스트
uv run pytest tests/ -q

# 군집 전체 E2E (stdio MCP, 모든 도구/리소스/프롬프트 + HITL/HOTL)
uv run pytest tests/e2e/ -q

# 실 LLM 루프 E2E — DeepSeek(deepseek-v4-flash)가 호스트 실행기 역할:
# tick → LLM이 GEP dispatch 프롬프트 실행 → distill → feedback → 두 번째 tick.
# 환경에 DEEPSEEK_API_KEY가 필요 (없으면 건너뜀).
DEEPSEEK_API_KEY=sk-... uv run pytest tests/e2e/ -m llm -q
# 선택: DEEPSEEK_BASE_URL (기본 https://api.deepseek.com),
#       DEEPSEEK_MODEL (기본 deepseek-v4-flash)

# 커버리지와 함께 실행
uv run pytest tests/ --cov=evolver --cov-report=term-missing

# 느린 테스트 제외 (CI 기본)
uv run pytest -m "not slow"

# 린트 + 포맷 검사 + 타입 검사
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src

# 모든 모듈 import 검증
python scripts/validate_modules.py
```

## 스크립트

| 스크립트 | 용도 |
|---|---|
| `scripts/a2a_export.py` | 자산을 A2A JSON으로 내보내기 |
| `scripts/a2a_ingest.py` | A2A 자산 가져오기 |
| `scripts/a2a_promote.py` | 후보 유전자를 정식 저장소로 승격 |
| `scripts/analyze_by_skill.py` | 스킬별 진화 이벤트 분석 |
| `scripts/baseline_snapshot.py` | 비교용 베이스라인 스냅샷 |
| `scripts/build_binaries.py` | PyInstaller 독립 실행 파일 빌드 헬퍼 |
| `scripts/check_changelog.py` | CHANGELOG와 버전 정합성 검사 |
| `scripts/env_inventory.py` | 환경 인벤토리 리포트 |
| `scripts/extract_log.py` | events.jsonl을 시각/유형으로 추출 |
| `scripts/generate_history.py` | GEP 이벤트 연대기 (Markdown) |
| `scripts/gep_append_event.py` | GEP 이벤트 수동 추가 |
| `scripts/gep_personality_report.py` | 퍼스널리티 HTML 리포트 |
| `scripts/harness_governance_check.py` | 하니스 거버넌스 감사 |
| `scripts/human_report.py` | Markdown 진화 리포트 생성 |
| `scripts/recall_verify_report.py` | recall/메모리 그래프 커버리지 |
| `scripts/recover_loop.py` | 데몬 루프 복구 진단 |
| `scripts/seed_merchants.py` | ATP 머천트 정의 시드 |
| `scripts/self_ab_acceptance.py` | 자체 A/B 수용 헬퍼 |
| `scripts/soak_env.py` / `scripts/soak_sprint24.py` | soak 환경 헬퍼 |
| `scripts/suggest_version.py` | 의미론적 버전 상승 제안 |
| `scripts/validate_modules.py` | 전체 import 검증 |
| `scripts/validate_suite.py` | import + 빠른 pytest 통합 게이트 |

## 아키텍처

### 진화 파이프라인 (7단계)

**이륙 전 체크**(`guards.py`) → 선택적으로 중단하고 SelfReport 스냅샷을 저장.

| 단계 | 모듈 | 역할 |
|---|---|---|
| 1. Collect | `collect.py` | 세션 로그, 실패 진단, `living_memory` |
| 2. Signals | `signals.py` | 신호 추출; guard / preflight / learning 키 |
| 3. Hub | `hub.py` | Hub 태스크/자산; hub 품질 게이트 데이터 |
| 4. Enrich | `enrich.py` | 메모리 그래프 조언, `bidirectional_memory_sync` |
| 5. Autopoiesis | `autopoiesis.py` | SelfReport, 생존 가능성, 항상성, repair bias |
| 6. Select | `select.py` | Gene/Capsule + 변이 카테고리 |
| 7. Dispatch | `dispatch.py` | GEP 프롬프트(`recall` + `autopoiesis_context`), solidify 상태 |

**사이클 후**(`post_cycle.py`) — ATP auto-buyer tick. **solidify**(`evolver solidify`)는 `gep/solidify.py`를 통해 별도 실행.

### 핵심 개념

- **Gene(유전자)** — 재사용 가능한 변이 전략 (signals_match → execution_trace)
- **Capsule(캡슐)** — 결과가 있는 구체적 실행 인스턴스
- **Epigenetics(후성유전학)** — 환경 인지 유전자 억제/활성화
- **Solidify(고체화)** — 검증된 변이를 코드베이스에 적용
- **Episode record(에피소드 기록)** — 자기 개선 1라운드의 런타임 기록; 소거 판정이 근거로 삼는 증거 원천
- **ATP** — 자율 서비스 시장을 위한 Agent 거래 프로토콜

## Node.js 레퍼런스와의 차이

- **라이선스**: Python 포트는 **Apache-2.0**으로 배포된다(공개 API·테스트 규약·사양에 기반한 클린룸 행동 등가 재구현). 상류 Node.js 레퍼런스 구현은 GPL-3.0-or-later.
- **소스 가시성**: Python 포트는 완전히 읽기 쉽고 문서화되어 있다. Node.js 코어는 난독화.
- **데이터베이스**: Python 포트는 SQLite 영속화를 위한 `ops/sqlite_store.py`를 추가(확장).
- **레시피 허브**: Python 포트는 `recipe/` 모듈을 포함(신규 기능).
- **WebUI 프론트엔드**: Python 포트는 SSE가 있는 인라인 JS 클라이언트(`webui/client/`)를 제공. 별도 빌드 SPA가 아니다.
- **통제 실험**: Python 포트는 `experiment/` 모듈을 내장하여 플라세보 대조와 표본량 게이트가 있는 엄격한 소거 판정을 제공.

## 보안 모델

Evolver는 파일 시스템과 네트워크에 접근한다. 가드레일은 다층에서 강제된다:

- **이륙 전 가드**: 노후화된 `.git/index.lock`과 보류 중인 rebase/merge를 자동 수리; 부하가 `EVOLVE_LOAD_MAX` 초과 시 사이클 건너뜀; 연속 수리 실패 시 저하 모드(수리 전용) 또는 하드 중단; 사용자 락(`~/.evolver/user.lock`, TTL 포함)으로 IDE 세션 중 변이 방지; `chore(release)` 커밋 근처에서는 진화 건너뜀
- **폭발 반경**: 모든 유전자는 `constraints.max_files`(통상 4–20)와 `forbidden_paths`를 선언; A2A 게이트 `A2A_MAX_FILES=5`, `A2A_MAX_LINES=200`; `EVOLVER_ROLLBACK_MODE=stash`는 적용 전 stash하고 실패 시 롤백
- **콘텐츠 무결성**: 자산 `asset_id`에 `sha256:` 해시 포함, 불일치 항목은 로드 시 조용히 건너뜀; `sanitize.py`가 Hub 자산의 위험 필드 제거
- **네트워크 안전**: Proxy는 기본적으로 `127.0.0.1`만 수신(`--host 0.0.0.0`은 명시적 옵트인); Hub 통신은 노드 비밀키 서명 + 남용 방지 텔레메트리; `webui-token`은 JWT를 발행하고 WebSocket 명령은 admin 롤 필요
- **사용자 비밀**: `redact.py`가 상호작용 로그에서 bearer 토큰 / API 키 / JWT / 비밀번호 제거; `.env`와 자격 증명은 절대 커밋되지 않음; 세션 기록은 WebUI 표시 전에 비식별화
- **군집 안전 (HITL + HOTL)**: HITL은 결정 단위 차단(고위험 solidify는 `gep/hitl.py` 통과, TTL 만료 시 fail-safe로 REJECT, subject 단위 멱등); HOTL은 감독 오버레이(pause/resume, veto, directive, 연속 저하 시 자동 일시정지). 모든 감독/승인 작업은 감사 로그에 기록

## 안티 예제 (동작하지 않는 사용법)

| 하지 말 것 | 이유 |
|---|---|
| git 저장소 없이(`/tmp` 등) evolver 실행 | 유전자는 폭발 반경 추적과 롤백에 git에 의존 |
| `OPENCLAW_WORKSPACE`를 프로덕션 서버로 지정 | Evolver는 코드 변이를 적용한다 — 격리 워크스페이스를 사용 |
| Hub 연결도 시드 유전자도 없이 `--loop` 실행 | 유전자 풀이 고갈된다; `EVOLVER_GENE_INERT_BAN_STREAK`를 높일 것 |
| 동일 워크스페이스에서 여러 evolver 실행 | 인스턴스 락이 방지한다; 프로젝트 격리는 `EVOLVER_SESSION_SCOPE` |
| `--solo` 모드에서 즉시 결과를 기대 | Solo에는 Hub 자산이 없다; 여러 사이클에 걸쳐 유전자 풀을 구축 |
| CI/CD에서 `--review` 사용 | 리뷰 모드는 stdin에서 멈춘다; 자동화는 `--loop` |
| 동일 저장소에서 Node.js와 Python evolver 혼용 | 상태 파일 형식이 다르다; 하나로 완전히 이전 |
| `EVOLVER_AUTOPOIESIS_WRITE=1` 설정 직후 `LESSONS_LEARNED.md` 확인 | 교훈은 사이클 완료 후 비동기로 기록된다 |
| 후보를 작성한 동일 컨텍스트에서 채점 | 페어 세션과 bench 규칙은 val 풀이를 독립 컨텍스트에서 요구한다 |

## Hub 연결

Hub(`A2A_HUB_URL`, 기본 `https://evomap.ai`)는 자산 발견(`GET /api/assets` 또는 `evolver fetch`), 태스크 마켓(`evolver sync` 또는 프록시 엔드포인트), ATP 정산, SSE + 폴링 양방향 이벤트 동기화를 제공한다. 연결은 완전히 선택적 — `--solo`는 모든 Hub 기능을 비활성화한다. 프록시가 연결 라이프사이클을 관리한다(시작 시 hello 하트비트, 도달 불가 시 지수 백오프 1s→30s, 남용 방지 텔레메트리, `A2A_NODE_SECRET_VERSION` 키 로테이션):

```bash
A2A_HUB_URL=https://your-hub.example.com uv run evolver proxy
```

## 문서

- [English README](README.md)
- [演进方案.md](演进方案.md) — 현재 헌장 (중국어)
- [TODO.md](TODO.md) — 그 작업 목록
- [CHANGELOG.md](CHANGELOG.md) — 라운드별 기록 (현재 1.113.0)
- [AGENTS.md](AGENTS.md) — 에이전트 통합 가이드, 코딩 표준, 함정
- [DEBUG.md](DEBUG.md) — 디버그 지침: dogfood와 인터록 버그의 근본 원인과 이전 가능한 교훈
- [RSI演进对照.md](RSI演进对照.md) — 논문 대조와 effective-L5 기록 (사료, 중국어)
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — 2026-09-01 감사 (사료, 중국어)
- [CONTRIBUTING.md](CONTRIBUTING.md) — 기여 가이드
- [SKILL.md](SKILL.md) — 스킬 사용 참조
- [docs/env-registry.md](docs/env-registry.md) — 환경 변수 레지스트리

## 라이선스

본 프로젝트는 **[Apache License 2.0](LICENSE)**에 따라 배포됩니다.

> **상위 프로젝트 계보에 대한 안내**: 본 프로젝트는 공개된 API 명세, 테스트 규약, 프로토콜 정의를 기반으로 바닥부터 독립적으로 클린룸 구현된 Python 포트입니다. 원본 Node.js 참조 구현체(`@evomap/evolver`)는 EvoMap에 의해 GPL-3.0-or-later로 배포되고 있습니다. 본 리포지토리는 Apache-2.0 라이선스로 유지됩니다.
