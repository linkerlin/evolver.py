# 🧬 evolver.py

[![Python 3.12+](https://img.shields.io/badge/Python-%3E%3D%203.12-blue.svg)](https://python.org/)

[`@evomap/evolver`](https://github.com/EvoMap/evolver)의 **Python 3.12+ 포트** — GEP 기반 AI 에이전트 자기 진화 엔진.

Node.js 레퍼런스 구현(v1.89.11)과의 **완전한 동작 동등성**을 목표로 하며, 현대적인 Python 도구 체인을 사용합니다.

## 빠른 시작

```bash
uv sync
uv run evolver              # 단일 진화 사이클
uv run evolver --loop       # 데몬 루프
uv run evolver --review     # 리뷰 모드
uv run evolver webui        # WebUI 대시보드
uv run evolver proxy        # 로컬 A2A 프록시
uv run evolver mcp          # MCP stdio 서버 (군집 진화 호스트 진입점)
```

## 주요 기능

- **GEP 프로토콜** — 감사 가능한 진화 자산(Gene / Capsule / Event)
- **7단계 진화 파이프라인** — collect → signals → hub → enrich → autopoiesis → select → dispatch
- **MCP 군집 진화 (v1.98+ 플래그십)** — 호스트 Agent를 stdio로 연결해 GEP 변이 프롬프트의 실행기로 인수(`evolver mcp` + `evolver_swarm` 프롬프트). HITL 승인 게이트 / HOTL 감독 / Hooks 양방향 브리지 / 스킬 브리지 / 통합 평가 피드백 E(저점수 시 자동 repair-bias 주입) / 적응적 변이 편향 / 인수 게이트 soak 리포트
- **진화 워크플로 (v1.110+, EvoX 수확)** — 협업 전체를 **YAML 워크플로**로 표현(diff 가능 → 진화 가능 자산). `agent` 스텝은 role/instruction을 선언해 호스트 실행기가 담당, `gate` 스텝은 검증 캐스케이드(ruff→mypy→pytest)를 엔진 측에서 실행, `approval` 스텝은 인간 승인 게이트. WAL 영속화·재개 가능. 번들 템플릿: `repair` / `innovate`
- **멀티 프로바이더 프록시** — Anthropic / Bedrock / Gemini / Vertex / Ollama / OpenAI (9개 라우트)
- **ATP 마켓플레이스** — 15개 CLI 서브커맨드(buy / sell / settle / dispute)
- **IDE 통합** — Cursor / Claude Code / Codex / Kiro / opencode 런타임 훅
- **Autopoiesis** — SelfReport + 항상성 + 자가 수리 (Python 오리지널 기능)

```bash
uv run evolver workflow templates               # repair / innovate 템플릿 목록
uv run evolver workflow run --template repair   # 복구 루프 시작 (YAML 파일도 가능)
uv run evolver workflow awaiting <id>           # 호스트 실행기 / 승인자의 현재 담당
```

## 설치

### 필요 조건

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- Anthropic API 키 (또는 호환 프로바이더)

### 개발 환경 설정

```bash
git clone https://github.com/EvoMap/evolver.py.git
cd evolver.py
uv sync
```

### 환경 변수

```bash
# .env 파일 (레포지토리 루트)
ANTHROPIC_API_KEY=sk-ant-...
A2A_HUB_URL=https://evomap.ai          # Hub 엔드포인트
EVOLVER_NO_PARENT_GIT=1                # 상위 .git 무시
OPENCLAW_WORKSPACE=/path/to/project    # 워크스페이스 루트
```

## 명령어 참조

| 명령어 | 설명 |
|--------|------|
| `uv run evolver` | 단일 진화 사이클 |
| `uv run evolver --loop` | 데몬 루프 |
| `uv run evolver --review` | 리뷰 모드 |
| `uv run evolver --solo` | 완전 오프라인 모드 |
| `uv run evolver solidify` | 보류 중인 변이 적용 |
| `uv run evolver start / stop / restart / status` | 데몬 라이프사이클 |
| `uv run evolver log` | 데몬 로그 표시 |
| `uv run evolver check / watch` | 헬스 모니터링 |
| `uv run evolver webui` | WebUI 대시보드 |
| `uv run evolver proxy` | A2A 프록시 시작 |
| `uv run evolver proxy-token` | 프록시 토큰 발행 |
| `uv run evolver setup-hooks --platform cursor` | IDE 훅 설치 |
| `uv run evolver self-report` | Autopoiesis 자가 진단 |
| `uv run evolver distill` | LLM 응답 증류 |
| `uv run evolver fetch <query>` | Hub에서 자산 가져오기 |
| `uv run evolver publish <id>` | Hub에 게시 |
| `uv run evolver sync` | Hub와 동기화 |
| `uv run evolver asset-log` | 자산 호출 로그 |
| `uv run evolver recipe list / show / apply` | 레시피 관리 |
| `uv run evolver skill2recipe` | 스킬을 레시피로 변환 |
| `uv run evolver atp balance / buy / orders / verify` | ATP 마켓플레이스 |

## 예제

| 예제 | 설명 |
|------|------|
| [`examples/swarm-quickstart/`](examples/swarm-quickstart/) | **군집 진화 전체 루프** — MCP 인수, tick→실행→distill→solidify→feedback, HITL/HOTL 운영(`--llm`로 DeepSeek가 실행기) |
| [`examples/hello-world/`](examples/hello-world/) | 단일 진화 사이클 |
| [`examples/daemon-loop/`](examples/daemon-loop/) | 데몬 루프와 라이프사이클 관리 |
| [`examples/proxy-basics/`](examples/proxy-basics/) | 프록시 설정과 curl API 예제 |
| [`examples/ide-hooks/`](examples/ide-hooks/) | 5개 플랫폼용 IDE 훅 |
| [`examples/solo-mode/`](examples/solo-mode/) | 완전 오프라인 격리 모드 |
| [`examples/self-report/`](examples/self-report/) | Autopoiesis 자가 진단 보고서 |
| [`examples/hub-publish-flow/`](examples/hub-publish-flow/) | 증류→재사용→게시 생명주기 |
| [`examples/skill2recipe/`](examples/skill2recipe/) | 스킬→레시피 합성 |
| [`examples/atp-quickstart/`](examples/atp-quickstart/) | ATP 마켓플레이스 데모 |

## 프로젝트 구조

```
evolver.py/
├── src/evolver/
│   ├── cli.py              # CLI 진입점
│   ├── config.py           # 런타임 설정
│   ├── gep/                # GEP 코어 (유전자, 캡슐, 프로토콜)
│   ├── evolve/             # 진화 파이프라인
│   ├── proxy/              # A2A 프록시
│   ├── webui/              # WebUI 대시보드
│   ├── ops/                # 운영 도구 (헬스, 수리, 트리거)
│   ├── atp/                # 에이전트 거래 프로토콜
│   └── adapters/           # IDE 훅 어댑터
├── tests/
├── examples/               # 실습 가이드 (모든 기능 커버)
└── docs/                   # 설계 문서와 로드맵
```

## 테스트

```bash
uv run pytest tests/ -q                    # 전체 테스트
uv run pytest -m "not slow" -q             # CI용 (느린 테스트 제외)
uv run ruff check src tests                # 린트
uv run mypy src                            # 타입 체크 (strict)
```

## 문서

- [README.md](README.md) — English
- [README.zh.md](README.zh.md) — 中文
- [README.ja-JP.md](README.ja-JP.md) — 日本語
- [SKILL.md](SKILL.md) — AI 에이전트용 스킬 정의
- [CONTRIBUTING.md](CONTRIBUTING.md) — 기여 가이드
- [AGENTS.md](AGENTS.md) — AI 에이전트 참조
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — wikiskill 감사 및 격차 로드맵 (중문)
- [TODO.md](TODO.md) — 갭 분석과 로드맵
- [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md) — v1.89.11 추적 계획 (중문)

## 라이선스

Apache-2.0 — 자세한 내용은 [LICENSE](LICENSE)를 참조하세요.

## 구현 상태

> **2026-09-05**: 패키지 버전 **1.111.0**. MCP 군집 진화 스택(v1.98–v1.111: 인수 루프, 평가 피드백 E, HITL/HOTL, Hooks/스킬 브리지, 적응적 변이, 인수 게이트 soak, YAML 워크플로 엔진) 완료 및 전면 그린(**3455 테스트 통과**, mypy strict 0 오류). 이 저장소 자체에서 5라운드 dogfood 실주행 — 인수 게이트 gated_runs=4. 잔여 깊이 격차는 [演进方案_wikiskill对照版.md](演进方案_wikiskill对照版.md)(중국어) 참조.

| 하위 시스템 | 상태 | 비고 |
|---|---|---|
| GEP 데이터 레이어 | ~90% | 시드 유전자 11×sha256; solidify 직접 테스트 + 학습 헬퍼 |
| GEP 인지 | ~80% | recall/reflection/distill; explore/curriculum 플래그 제어 |
| 진화 파이프라인 | ~90% | 7 페이즈 + Autopoiesis + 하드 타임아웃; 적용 완료 유전자 쿨다운(v1.111) |
| MCP 군집 진화 | ~97% | 인수 루프 + E 피드백 + HITL/HOTL + Hooks/스킬/워크플로 도구; dogfood 5라운드 |
| 워크플로 엔진 | ~90% | WAL 영속 스텝(script/foreach/if/agent/approval/gate); YAML + 롤 + 템플릿(v1.110) |
| 인수 게이트 | ~85% | shadow soak + gate-report 판정; 강제 집행 스위치는 인간 결정 |
| 프록시 인프라 | ~85% | 멀티 프로바이더, 토큰 재사용, 경로 CLI 플래그, 포트 **8081** |
| ATP 마켓 | ~65% | 로컬 정산; Hub 상용 E2E 보류 |
| IDE 어댑터 | ~85% | 런타임 훅 + py_compile 문법 가드 + MCP 인프로세스 브리지 |
| Ops / Solo | ~85% | 라이프사이클, force-update, --solo |
| WebUI | ~70% | SSR 대시보드 + GitHub observer |
| Validator | ~50% | 샌드박스 기반; 프로덕션 네트워크 격리 보류 |
| 문서 / 릴리스 | ~90% | CHANGELOG + 버전 **1.111.0**; 멀티 OS CI |

## 주요 환경 변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `EVOLVER_HOME` | `~/.evomap` | 사용자 상태 디렉터리 |
| `GEP_ASSETS_DIR` | `<ws>/.evolver/gep/` | GEP 에셋 저장소 |
| `EVOLUTION_DIR` | `<ws>/memory/evolution/` | 진화 상태 |
| `A2A_HUB_URL` | `https://evomap.ai` | Hub 엔드포인트 |
| `EVOLVE_STRATEGY` | `balanced` | 진화 전략 |
| `EVOLVER_AUTOPOIESIS` | `1` | Autopoiesis 페이즈 활성화 |
| `EVOLVER_MEMORY_GRAPH_MAX_SIZE_MB` | `100` | memory_graph.jsonl 로테이션 임계값 |
| `EVOLVER_ANTI_ABUSE_TELEMETRY` | `heartbeat` | 남용 방지 텔레메트리 모드 |
| `EVOLVER_PROXY_PORT` | `8081` | 프록시 포트 |
| `EVOLVER_NO_PARENT_GIT` | （없음） | `.git` 탐색 비활성화 |
| `EVOLVER_ROLLBACK_MODE` | `stash` | 롤백 전략 |
| `EVOLVER_HITL_MODE` | `off` | HITL 승인 게이트(`on` 시 고위험 solidify는 인간 승인 대기) |
| `EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK` | `3` | HOTL 트립와이어 — N회 연속 저하 시 자동 일시정지 |
| `EVOLVER_FEEDBACK_DEGRADED_THRESHOLD` | `0.5` | 군집 피드백 저하 임계값(미만 시 repair-bias 주입) |
| `EVOLVER_APPLIED_GENE_COOLDOWN_EVENTS` | `5` | 적용 완료 유전자 쿨다운 창(선택 점수 페널티) |
| `EVOLVER_GATE_SOAK_MIN_RUNS` | `20` | 인수 게이트 승격 판정 최소 샘플 수 |
